#!/usr/bin/env bash
set -e

docker compose -f docker-compose.prod.yml exec backend python -m services.agents.build_knowledge_index
