import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.competition_agent.controlled_qoder_tools import (
    CONTROLLED_QODER_TOOL_NAMES,
    ControlledQoderToolError,
    ControlledQoderToolSession,
)
from services.competition_agent.planning import calculation_plan


POSCAR = """MoS2
1.0
3.18 0 0
-1.59 2.75396 0
0 0 20
Mo S
1 2
Direct
0 0 0.5
0.333333 0.666667 0.58
0.666667 0.333333 0.42
"""


class ControlledQoderToolTests(unittest.TestCase):
    def payload(self):
        structure_id = "00000000-0000-4000-8000-000000000001"
        result_id = "00000000-0000-4000-8000-000000000002"
        return {
            "files": [
                {
                    "id": structure_id,
                    "name": "POSCAR",
                    "category": "structure",
                    "content": POSCAR,
                },
                {
                    "id": result_id,
                    "name": "OUTCAR",
                    "category": "result",
                    "content": "free  energy   TOTEN  = -12.34 eV\nSECRET-MARKER",
                },
            ],
            "workflow": {
                "id": "00000000-0000-4000-8000-000000000003",
                "status": "running",
                "steps": [{"key": "relax", "status": "succeeded"}],
            },
            "plan": calculation_plan("计算 MoS2 能带", [{
                "id": structure_id,
                "name": "POSCAR",
                "category": "structure",
                "content": POSCAR,
            }]),
        }

    def test_context_index_never_contains_authorized_file_contents(self):
        session = ControlledQoderToolSession(self.payload())
        index = session.context_index()
        self.assertNotIn("SECRET-MARKER", repr(index))
        self.assertNotIn(POSCAR, repr(index))
        self.assertEqual(list(CONTROLLED_QODER_TOOL_NAMES), index["available_tools"])

    def test_tools_return_only_authorized_read_only_views_and_record_real_calls(self):
        payload = self.payload()
        session = ControlledQoderToolSession(
            payload,
            structure_search=lambda query, limit: {
                "items": [{"id": "qmof-a", "formula": "MoS2", "source": "QMOF"}],
                "total": 1,
                "sources": ["QMOF"],
            },
        )
        searched = session.invoke("search_structure_library", {"query": "MoS2", "limit": 5})
        inspected = session.invoke("inspect_uploaded_structures", {
            "file_ids": [payload["files"][0]["id"]],
        })
        analyzed = session.invoke("analyze_vasp_results", {
            "file_ids": [payload["files"][1]["id"]],
        })
        workflow = session.invoke("read_workflow_summary", {
            "workflow_id": payload["workflow"]["id"],
        })
        draft = session.invoke("prepare_workflow_draft", {})

        self.assertEqual("qmof-a", searched["items"][0]["id"])
        self.assertEqual(3, inspected["items"][0]["summary"]["atom_count"])
        self.assertNotIn("content", repr(inspected))
        self.assertEqual(-12.34, analyzed["items"][0]["facts"]["final_energy_eV"])
        self.assertNotIn("SECRET-MARKER", repr(analyzed))
        self.assertEqual("running", workflow["status"])
        self.assertEqual(["relax", "scf", "band"], draft["steps"])
        self.assertNotIn(POSCAR, repr(draft))
        self.assertNotIn("'files':", repr(draft))
        self.assertEqual(
            list(CONTROLLED_QODER_TOOL_NAMES),
            [item["name"] for item in session.calls],
        )
        self.assertTrue(all(item["status"] == "succeeded" for item in session.calls))

    def test_tools_reject_unmounted_ids_and_stop_after_the_call_budget(self):
        session = ControlledQoderToolSession(self.payload(), max_calls=2)
        with self.assertRaisesRegex(ControlledQoderToolError, "not authorized"):
            session.invoke("analyze_vasp_results", {"file_ids": ["unknown"]})
        session.invoke("prepare_workflow_draft", {})
        with self.assertRaisesRegex(ControlledQoderToolError, "call limit"):
            session.invoke("prepare_workflow_draft", {})
        self.assertEqual("failed", session.calls[0]["status"])
        self.assertEqual(2, len(session.calls))

    def test_structure_search_has_bounded_inputs(self):
        session = ControlledQoderToolSession(self.payload())
        with self.assertRaises(ControlledQoderToolError):
            session.invoke("search_structure_library", {"query": "x" * 101, "limit": 5})
        with self.assertRaises(ControlledQoderToolError):
            session.invoke("search_structure_library", {"query": "MoS2", "limit": 1000})


if __name__ == "__main__":
    unittest.main()
