from __future__ import annotations

from fastapi import APIRouter, Depends

from competition_authz import require_viewer_or_operator
from models import User
from services.competition_cluster_resources import ClusterResourceService


router = APIRouter(prefix="/competition", tags=["competition-cluster"])
_cluster_resource_service = ClusterResourceService()


def get_cluster_resource_service() -> ClusterResourceService:
    return _cluster_resource_service


@router.get("/cluster-resources")
def cluster_resources(
    _user: User = Depends(require_viewer_or_operator),
    service: ClusterResourceService = Depends(get_cluster_resource_service),
):
    return service.get_snapshot()
