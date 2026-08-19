import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, selectinload

from auth_identity import get_current_user
from database import Base
from database import get_db
from models import User
from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowFile,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
    canonical_json,
)
from services.competition_results import (
    CompetitionResultService,
    ExistingVaspScientificParser,
    ResultServiceError,
    VerifiedArtifact,
)
from routers.competition_workflows import get_competition_result_service, router


WORKFLOW_ID = "11111111-1111-4111-8111-111111111111"
FAILED_WORKFLOW_ID = "22222222-2222-4222-8222-222222222222"
RELEASE_COMMIT = "a" * 40
STEP_KEYS = ("relax", "scf", "band", "dos")


class ExistingVaspScientificParserTests(unittest.TestCase):
    def test_structure_exports_use_the_binary_and_text_buffers_required_by_ase(self):
        path = Path("competition_templates/mos2_v1/POSCAR").resolve()
        source = VerifiedArtifact(
            path=path,
            relative_path="fixture/POSCAR",
            logical_path="POSCAR",
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size_bytes=path.stat().st_size,
            attempt_id=None,
            step_key="relax",
        )
        parser = ExistingVaspScientificParser()

        cif = parser.export_artifact("structure-cif", {"relax": source})
        poscar = parser.export_artifact("structure-poscar", {"relax": source})

        self.assertTrue(cif.startswith(b"data_"))
        self.assertIn(b"_cell_length_a", cif)
        self.assertIn(b"Mo", poscar)
        self.assertIn(b"Direct", poscar)


class FakeScientificParser:
    def __init__(self):
        self.calls = []
        self.fail_detail = False
        self.invalid_detail = False

    @staticmethod
    def _detail(workflow_id):
        structure = {
            "symbols": ["Mo", "S", "S"],
            "positions": [[0.0, 0.0, 10.0], [1.5, 0.9, 11.5], [1.5, 0.9, 8.5]],
            "cell": [[3.18, 0.0, 0.0], [-1.59, 2.75, 0.0], [0.0, 0.0, 20.0]],
            "pbc": [True, True, True],
        }
        return {
            "db": {"dbname": "107 Cup workflow results"},
            "row": {
                "id": workflow_id,
                "formula": "MoS2",
                "energy": -22.4,
                "fmax": 0.006,
                "natoms": 3,
                "pbc": [True, True, True],
            },
            "properties": {
                "spacegroup": "P-6m2",
                "bandgap_eV": 1.7,
                "vbm_eV": -0.1,
                "cbm_eV": 1.6,
            },
            "structure": structure,
            "crystal": {
                "lattice": {
                    "a": 3.18,
                    "b": 3.18,
                    "c": 20.0,
                    "alpha": 90.0,
                    "beta": 90.0,
                    "gamma": 120.0,
                    "volume": 175.0,
                },
                "density_g_cm3": 0.9,
                "dimensionality": 3,
                "atomic_positions_frac": [
                    {"element": "Mo", "x": 0.0, "y": 0.0, "z": 0.5},
                    {"element": "S", "x": 0.667, "y": 0.333, "z": 0.58},
                    {"element": "S", "x": 0.667, "y": 0.333, "z": 0.42},
                ],
            },
            "capabilities": {
                "structure_export": True,
                "band_plot": True,
                "dos_plot": True,
                "band_data": True,
                "dos_data": True,
            },
        }

    def build_detail(self, workflow_id, sources):
        self.calls.append(("detail", workflow_id, tuple(sorted(sources))))
        if self.fail_detail:
            raise ValueError("private parser failure")
        if self.invalid_detail:
            return {"row": {"formula": "MoS2"}}
        return self._detail(workflow_id)

    def render_plot(self, kind, source):
        self.calls.append(("plot", kind, source.relative_path))
        return f"base64-{kind}"

    def export_artifact(self, kind, sources):
        self.calls.append(("artifact", kind, tuple(sorted(sources))))
        payloads = {
            "structure-cif": b"data_MoS2\n",
            "structure-poscar": b"MoS2\n1.0\n",
            "band-data": b"# band data\n",
            "dos-data": b"PK\x03\x04dos",
        }
        return payloads[kind]


class CompetitionResultServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.workflow_root = self.root / "data" / "workflows"
        self.releases_root = self.root / "releases"
        self.workflow_root.mkdir(parents=True)
        release = self.releases_root / RELEASE_COMMIT
        release.mkdir(parents=True)
        manifest = "".join(
            [
                f"{'1' * 64}  source/backend/main_107cup.py\n",
                f"{'2' * 64}  frontend-dist/index.html\n",
            ]
        )
        (release / "manifest.txt").write_text(manifest, encoding="utf-8", newline="\n")
        manifest_digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        (release / "manifest.sha256").write_text(
            f"{manifest_digest}  manifest.txt\n", encoding="ascii", newline="\n"
        )

        self.engine = create_engine(f"sqlite:///{self.root / 'test.sqlite'}")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.parser = FakeScientificParser()
        self.service = CompetitionResultService(
            workflow_root=self.workflow_root,
            releases_root=self.releases_root,
            parser=self.parser,
        )
        with Session(self.engine) as session:
            owner = User(
                email="operator@example.com",
                password_hash="hash",
                name="Operator",
                alias="operator",
                role="operator",
            )
            session.add(owner)
            session.flush()
            self.owner_id = owner.id
            other = User(
                email="other@example.com",
                password_hash="hash",
                name="Other",
                alias="other",
                role="operator",
            )
            viewer = User(
                email="viewer@example.com",
                password_hash="hash",
                name="Viewer",
                alias="viewer",
                role="viewer",
            )
            session.add_all([other, viewer])
            session.flush()
            self.other_id = other.id
            self.viewer_id = viewer.id
            session.add(
                WorkflowTemplate(
                    template_key="mos2",
                    version="mos2_v1",
                    definition_json={"version": "mos2_v1", "steps": list(STEP_KEYS)},
                )
            )
            self._create_success(session)
            self._create_scientific_failure(session)
            session.commit()
        self.identity_id = self.owner_id
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")

        def test_db():
            with Session(self.engine) as session:
                yield session

        def identity(db: Session = Depends(get_db)):
            return db.get(User, self.identity_id)

        self.app.dependency_overrides[get_db] = test_db
        self.app.dependency_overrides[get_current_user] = identity
        self.app.dependency_overrides[get_competition_result_service] = lambda: self.service
        self.client = TestClient(self.app)

    @staticmethod
    def _acceptance(*, accepted, names, reason_code=None):
        report = {
            "accepted": accepted,
            "reason_code": reason_code,
            "checks": [{"name": "scheduler_state", "passed": True}],
            "measurements": {
                "elapsed_wall_seconds": 1.5,
                "process_tree_peak_rss_kbytes": 2048,
                "vasp_version": "6.4.2",
                "vaspkit_version": "1.5.1",
            },
            "artifacts": [
                {"name": name, "sha256": "0" * 64, "size_bytes": 1}
                for name in names
            ],
        }
        digest = hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()
        return report, digest

    def _add_file(self, session, run, attempt, logical_path, content):
        directory = self.workflow_root / run.id / "attempts" / attempt.id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / logical_path
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        session.add(
            WorkflowFile(
                id=str(uuid.uuid4()),
                workflow_id=run.id,
                attempt_id=attempt.id,
                owner_id=run.owner_id,
                relative_path=f"{run.id}/attempts/{attempt.id}/{logical_path}",
                size_bytes=len(content),
                sha256=digest,
                source_kind="attempt_output",
                metadata_json={
                    "accepted": True,
                    "logical_path": logical_path,
                    "output_role": "scientific_acceptance_evidence",
                    "step_key": attempt.step.step_key,
                    "release_commit": run.release_commit,
                },
            )
        )
        return {"name": logical_path, "sha256": digest, "size_bytes": len(content)}

    def _add_attempt(self, session, run, step, *, job_id, accepted=True, reason_code=None):
        attempt = WorkflowAttempt(
            id=str(uuid.uuid4()),
            step=step,
            attempt_number=1,
            status="succeeded" if accepted else "scientific_failed",
            slurm_job_id=str(job_id),
            working_directory=str(self.workflow_root / run.id / "attempts" / "pending"),
            metadata_json={},
        )
        session.add(attempt)
        session.flush()
        attempt.working_directory = str(self.workflow_root / run.id / "attempts" / attempt.id)
        names = ["CONTCAR", "vasprun.xml"] if step.step_key == "relax" else ["vasprun.xml"]
        artifacts = [
            self._add_file(session, run, attempt, name, f"{run.id}:{step.step_key}:{name}".encode())
            for name in names
        ]
        report = {
            "accepted": accepted,
            "reason_code": reason_code,
            "checks": [
                {
                    "name": "electronic_convergence",
                    "passed": accepted,
                    **({"reason_code": reason_code} if reason_code else {}),
                }
            ],
            "measurements": {
                "elapsed_wall_seconds": 1.5,
                "process_tree_peak_rss_kbytes": 2048,
                "vasp_version": "6.4.2",
                "vaspkit_version": "1.5.1",
            },
            "artifacts": artifacts,
        }
        attempt.metadata_json = {
            "scheduler_observation": {
                "job_id": str(job_id),
                "state": "succeeded",
                "raw_state": "COMPLETED",
                "exit_code": "0:0",
                "reason": "None",
                "stale": False,
                "error_code": None,
            },
            "scientific_acceptance": report,
            "scientific_acceptance_sha256": hashlib.sha256(
                canonical_json(report).encode("utf-8")
            ).hexdigest(),
        }
        return attempt

    def _create_success(self, session):
        run = WorkflowRun(
            id=WORKFLOW_ID,
            owner_id=self.owner_id,
            template_version="mos2_v1",
            material="MoS2",
            source_kind="builtin",
            status="succeeded",
            input_sha256="3" * 64,
            release_commit=RELEASE_COMMIT,
            metadata_json={
                "normalized_payload": {"template_version": "mos2_v1"},
                "input_manifest": [{"logical_path": "relax/POSCAR", "sha256": "4" * 64}],
            },
        )
        session.add(run)
        session.flush()
        for index, key in enumerate(STEP_KEYS):
            step = WorkflowStep(
                workflow=run,
                step_key=key,
                position=index,
                status="succeeded",
                parameters_json={"depends_on": [], "parameters": {}},
            )
            session.add(step)
            session.flush()
            self._add_attempt(session, run, step, job_id=41001 + index)
        for sequence, event_type in enumerate(("draft_created", "workflow_status_changed"), 1):
            session.add(
                WorkflowEvent(
                    workflow=run,
                    sequence=sequence,
                    event_type=event_type,
                    payload_json={"status": "succeeded"} if sequence == 2 else {},
                )
            )

    def _create_scientific_failure(self, session):
        run = WorkflowRun(
            id=FAILED_WORKFLOW_ID,
            owner_id=self.owner_id,
            template_version="mos2_v1",
            material="MoS2",
            source_kind="builtin",
            status="failed",
            input_sha256="5" * 64,
            release_commit=RELEASE_COMMIT,
            metadata_json={"normalized_payload": {"template_version": "mos2_v1"}},
        )
        session.add(run)
        session.flush()
        for index, key in enumerate(STEP_KEYS):
            status = "succeeded" if key == "relax" else "scientific_failed" if key == "scf" else "blocked"
            step = WorkflowStep(
                workflow=run,
                step_key=key,
                position=index,
                status=status,
                parameters_json={"depends_on": [], "parameters": {}},
            )
            session.add(step)
            session.flush()
            if key == "relax":
                self._add_attempt(session, run, step, job_id=42001)
            elif key == "scf":
                self._add_attempt(
                    session,
                    run,
                    step,
                    job_id=42002,
                    accepted=False,
                    reason_code="electronic_not_converged",
                )

    def _load(self, session, workflow_id):
        return session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == workflow_id)
            .options(
                selectinload(WorkflowRun.owner),
                selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
                selectinload(WorkflowRun.files),
                selectinload(WorkflowRun.events),
            )
        )

    def test_success_detail_requires_four_accepted_steps_and_provenance(self):
        with Session(self.engine) as session:
            detail = self.service.detail(self._load(session, WORKFLOW_ID))

        self.assertEqual("succeeded", detail["status"])
        self.assertEqual(WORKFLOW_ID, detail["workflow_id"])
        self.assertEqual(["relax", "scf", "band", "dos"], [step["key"] for step in detail["steps"]])
        self.assertTrue(all(step["accepted"] is True for step in detail["steps"]))
        self.assertEqual("MoS2", detail["vasp_detail"]["row"]["formula"])
        self.assertEqual(
            ["structure-cif", "structure-poscar", "band-data", "dos-data", "evidence-bundle"],
            detail["artifacts"],
        )
        provenance = detail["vasp_detail"]["provenance"]
        self.assertEqual({"relax", "scf", "band", "dos"}, set(provenance))
        self.assertTrue(all(len(value["sha256"]) == 64 for value in provenance.values()))

    def test_scientific_failure_never_builds_success_detail(self):
        with Session(self.engine) as session:
            detail = self.service.detail(self._load(session, FAILED_WORKFLOW_ID))

        self.assertEqual("failed", detail["status"])
        self.assertNotIn("vasp_detail", detail)
        self.assertEqual(["evidence-bundle"], detail["artifacts"])
        self.assertEqual("scf", detail["failure_evidence"]["step"])
        self.assertEqual("electronic_not_converged", detail["failure_evidence"]["reason"])
        self.assertEqual([], [step for step in detail["steps"] if step["key"] in {"band", "dos"} and step["job_id"]])

    def test_missing_or_changed_source_fails_closed(self):
        with Session(self.engine) as session:
            run = self._load(session, WORKFLOW_ID)
            band = next(step for step in run.steps if step.step_key == "band")
            source = next(row for row in run.files if row.attempt_id == band.attempts[0].id)
            path = self.workflow_root / source.relative_path
            path.unlink()
            missing = self.service.detail(run)
            self.assertEqual("parse-error", missing["status"])
            self.assertNotIn("vasp_detail", missing)
            self.assertEqual("band", missing["failure_evidence"]["step"])
            self.assertEqual(["vasprun.xml"], missing["failure_evidence"]["missing_files"])

            path.write_bytes(b"tampered")
            changed = self.service.detail(run)
            self.assertEqual("parse-error", changed["status"])
            self.assertEqual("artifact_hash_mismatch", changed["failure_evidence"]["reason"])
            self.assertEqual("band", changed["failure_evidence"]["step"])

    def test_parser_failure_is_classified_in_result_summary(self):
        self.parser.fail_detail = True
        with Session(self.engine) as session:
            summary = self.service.summary(self._load(session, WORKFLOW_ID))

        self.assertEqual("parse-error", summary["status"])
        self.assertEqual("scientific_parse_failed", summary["failure_evidence"]["reason"])
        self.assertNotIn("private parser failure", json.dumps(summary))

    def test_incomplete_scientific_detail_is_never_reported_as_success(self):
        self.parser.invalid_detail = True
        with Session(self.engine) as session:
            detail = self.service.detail(self._load(session, WORKFLOW_ID))

        self.assertEqual("parse-error", detail["status"])
        self.assertNotIn("vasp_detail", detail)
        self.assertEqual("scientific_contract_invalid", detail["failure_evidence"]["reason"])

    def test_path_escape_fails_closed_without_reading_outside_file(self):
        outside = self.root / "outside.xml"
        outside.write_bytes(b"outside")
        with Session(self.engine) as session:
            run = self._load(session, WORKFLOW_ID)
            dos = next(step for step in run.steps if step.step_key == "dos")
            source = next(row for row in run.files if row.attempt_id == dos.attempts[0].id)
            source.relative_path = "../outside.xml"
            session.flush()
            detail = self.service.detail(run)

        self.assertEqual("parse-error", detail["status"])
        self.assertEqual("artifact_path_invalid", detail["failure_evidence"]["reason"])
        self.assertNotIn(str(outside), json.dumps(detail))

    def test_windows_style_path_escape_is_rejected_as_noncanonical(self):
        with Session(self.engine) as session:
            run = self._load(session, WORKFLOW_ID)
            dos = next(step for step in run.steps if step.step_key == "dos")
            source = next(row for row in run.files if row.attempt_id == dos.attempts[0].id)
            source.relative_path = "..\\outside.xml"
            session.flush()
            detail = self.service.detail(run)

        self.assertEqual("parse-error", detail["status"])
        self.assertEqual("artifact_path_invalid", detail["failure_evidence"]["reason"])
        self.assertEqual("dos", detail["failure_evidence"]["step"])

    def test_plots_and_scientific_downloads_use_verified_sources(self):
        with Session(self.engine) as session:
            run = self._load(session, WORKFLOW_ID)
            band_plot = self.service.plot(run, "band")
            dos_plot = self.service.plot(run, "dos")
            band_data = self.service.artifact(session, run, "band-data")
            dos_data = self.service.artifact(session, run, "dos-data")

        self.assertEqual("base64-band", band_plot["image_base64"])
        self.assertEqual("base64-dos", dos_plot["image_base64"])
        self.assertEqual(b"# band data\n", band_data.content)
        self.assertEqual("text/plain; charset=utf-8", band_data.media_type)
        self.assertEqual(b"PK\x03\x04dos", dos_data.content)
        self.assertEqual("application/zip", dos_data.media_type)

    def test_evidence_bundle_is_deterministic_and_contains_no_absolute_paths(self):
        with Session(self.engine) as session:
            run = self._load(session, WORKFLOW_ID)
            first = self.service.artifact(session, run, "evidence-bundle")
            second = self.service.artifact(session, run, "evidence-bundle")

        self.assertEqual(first.content, second.content)
        payload = json.loads(first.content)
        self.assertEqual("lmatelab-107cup-evidence-v1", payload["schema"])
        self.assertEqual(WORKFLOW_ID, payload["workflow"]["id"])
        self.assertEqual(RELEASE_COMMIT, payload["release"]["commit"])
        self.assertEqual(2, len(payload["release"]["manifest"]))
        self.assertRegex(payload["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn(str(self.root), first.content.decode("utf-8"))

    def test_unknown_artifact_kind_is_rejected(self):
        with Session(self.engine) as session:
            run = self._load(session, WORKFLOW_ID)
            with self.assertRaises(ResultServiceError) as raised:
                self.service.artifact(session, run, "shell-output")
        self.assertEqual("artifact_kind_invalid", raised.exception.code)

    def test_live_routes_expose_success_failure_plots_and_database(self):
        results = self.client.get("/api/competition/results")
        success = self.client.get(f"/api/competition/results/{WORKFLOW_ID}")
        failure = self.client.get(f"/api/competition/results/{FAILED_WORKFLOW_ID}")
        band = self.client.get(f"/api/competition/results/{WORKFLOW_ID}/band-plot")
        database = self.client.get(
            "/api/competition/vasp/records",
            params={"elements": "Mo,S", "element_mode": "only", "page": 1, "page_size": 20},
        )

        self.assertEqual(200, results.status_code, results.text)
        self.assertEqual(2, results.json()["total"])
        self.assertEqual(200, success.status_code, success.text)
        self.assertEqual("succeeded", success.json()["status"])
        self.assertEqual(200, failure.status_code, failure.text)
        self.assertEqual("electronic_not_converged", failure.json()["failure_evidence"]["reason"])
        self.assertEqual("base64-band", band.json()["image_base64"])
        self.assertEqual(200, database.status_code, database.text)
        self.assertEqual(2, database.json()["total"])
        self.assertEqual(["Mo", "S"], database.json()["available_elements"])

    def test_operator_cannot_read_another_operators_results_but_viewer_can(self):
        self.identity_id = self.other_id
        denied = self.client.get(f"/api/competition/results/{WORKFLOW_ID}")
        self.assertEqual(404, denied.status_code, denied.text)

        self.identity_id = self.viewer_id
        visible = self.client.get(f"/api/competition/results/{WORKFLOW_ID}")
        self.assertEqual(200, visible.status_code, visible.text)

    def test_viewer_and_operator_download_identical_evidence_bundle(self):
        operator = self.client.get(
            f"/api/competition/results/{WORKFLOW_ID}/artifacts/evidence-bundle"
        )
        self.identity_id = self.viewer_id
        viewer = self.client.get(
            f"/api/competition/results/{WORKFLOW_ID}/artifacts/evidence-bundle"
        )

        self.assertEqual(200, operator.status_code, operator.text)
        self.assertEqual(operator.content, viewer.content)
        self.assertEqual("no-store", operator.headers["cache-control"])
        self.assertIn("evidence-bundle.json", operator.headers["content-disposition"])

    def test_invalid_result_filters_and_artifacts_are_rejected(self):
        invalid_status = self.client.get("/api/competition/results", params={"status": "running"})
        invalid_elements = self.client.get(
            "/api/competition/vasp/records", params={"elements": "Mo,../S"}
        )
        invalid_artifact = self.client.get(
            f"/api/competition/results/{WORKFLOW_ID}/artifacts/shell-output"
        )

        self.assertEqual(400, invalid_status.status_code, invalid_status.text)
        self.assertEqual(400, invalid_elements.status_code, invalid_elements.text)
        self.assertEqual(400, invalid_artifact.status_code, invalid_artifact.text)
        self.assertEqual("artifact_kind_invalid", invalid_artifact.headers["x-error-code"])


if __name__ == "__main__":
    unittest.main()
