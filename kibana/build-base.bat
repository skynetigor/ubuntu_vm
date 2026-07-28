@echo off
docker build ^
  -f kibana/Dockerfile.base ^
  --build-arg KIBANA_BRANCH=%KIBANA_BRANCH% ^
  --build-arg KIBANA_REPO_URL=%KIBANA_REPO_URL% ^
  -t kibana-base:latest ^
  kibana/
