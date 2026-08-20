#!/usr/bin/env bash
# Start the nine TraceFlix services on localhost for a frontend/demo run.
#
# Ports mirror the mesh of Fig. 4.2: gateway fans out to user, search and movie;
# user calls auth + recommendation; search and recommendation both call catalog;
# movie calls actor + review.
#
# Usage:  ./run-local.sh start | stop | status
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LOGS="${TRACEFLIX_LOGS:-$HERE/.run-logs}"
PIDS="$LOGS/pids"

GATEWAY=8080; MOVIE=8081; USER=8082; SEARCH=8083; ACTOR=8084
REVIEW=8085; AUTH=8086; RECO=8087; CATALOG=8088

jar() { echo "$HERE/$1-service/target/$1-service-0.0.1-SNAPSHOT.jar"; }

launch() {
  local name="$1"; shift
  local j; j="$(jar "$name")"
  if [ ! -f "$j" ]; then echo "MISSING JAR: $j" >&2; return 1; fi
  java -jar "$j" "$@" >"$LOGS/$name.log" 2>&1 &
  echo "$name $!" >> "$PIDS"
  echo "  started $name (pid $!)"
}

start() {
  mkdir -p "$LOGS"; : > "$PIDS"
  echo "starting TraceFlix mesh..."
  # leaves first, then the services that depend on them
  launch catalog        --server.port=$CATALOG
  launch actor          --server.port=$ACTOR
  launch review         --server.port=$REVIEW
  launch auth           --server.port=$AUTH
  launch recommendation --server.port=$RECO \
                        --catalog-service.url=http://localhost:$CATALOG
  launch search         --server.port=$SEARCH \
                        --catalog-service.url=http://localhost:$CATALOG
  launch movie          --server.port=$MOVIE \
                        --actor-service.url=http://localhost:$ACTOR/api/actors \
                        --review-service.url=http://localhost:$REVIEW/api/reviews
  launch user           --server.port=$USER \
                        --auth-service.url=http://localhost:$AUTH \
                        --recommendation-service.url=http://localhost:$RECO/api/recommendations
  launch gateway        --server.port=$GATEWAY \
                        --movie-service.url=http://localhost:$MOVIE \
                        --user-service.url=http://localhost:$USER \
                        --search-service.url=http://localhost:$SEARCH
  echo "logs in $LOGS"
}

stop() {
  [ -f "$PIDS" ] || { echo "no pid file"; return 0; }
  while read -r name pid; do
    kill "$pid" 2>/dev/null && echo "  stopped $name ($pid)"
  done < "$PIDS"
  rm -f "$PIDS"
}

status() {
  for p in $CATALOG $ACTOR $REVIEW $AUTH $RECO $SEARCH $MOVIE $USER $GATEWAY; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:$p/actuator/health" 2>/dev/null)
    printf '  port %-5s health=%s\n' "$p" "${code:-down}"
  done
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
