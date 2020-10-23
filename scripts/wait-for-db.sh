#!/bin/bash

set -e

CMD="$@"

while ! PGPASSWORD=$POSTGRES_PASSWORD pg_isready -h $POSTGRES_HOST -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE_RELAYER" > /dev/null 2> /dev/null; do
  echo "Waiting for database to be ready ..."
  sleep 5
done

>&2 echo "Database is ready!"

exec $CMD
