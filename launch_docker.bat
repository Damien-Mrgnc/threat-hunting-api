docker compose -f infra/docker-compose.yml down --remove-orphans
docker compose -f infra/docker-compose.yml up -d --build --scale api=3