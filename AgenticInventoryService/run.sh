#!/bin/bash
# poor man's makefile

# Check if an argument is provided
if [ -z "$1" ]; then
  echo "Error: Please provide a valid argument such as 'api', 'test', 'frontend', etc."
  exit 1
fi

# Check the value of the first argument
if [ "$1" == "api" ]; then
  echo "Running FastAPI with Uvicorn..."
  poetry run uvicorn agentic_inventory.main:app --host=0.0.0.0 --port=8080 --use-colors
elif [ "$1" == "gunicorn" ]; then
  echo "Running Gunicorn server..."
  poetry run gunicorn agentic_inventory.main:app -c agentic_inventory.conf.py -w 2
elif [ "$1" == "console" ]; then
  echo "Running console"
  export PYTHONPATH=$(pwd)
  shift # swallow first arg
  poetry run python agentic_inventory/utils/console.py "$@"
elif [ "$1" == "frontend" ]; then
  echo "Running streamlit development server..."
  poetry run streamlit run agentic_inventory/frontend/app.py
elif [ "$1" == "api_gen" ]; then
  echo "Running Swagger Generation"
  export PYTHONPATH=$(pwd)
  if [ "$2" == "console" ]; then
    poetry run python agentic_inventory/utils/api_gen.py
  else
    poetry run python agentic_inventory/utils/api_gen.py > AzureApi/service_swagger_spec_v1.openapi.json
  fi
elif [ "$1" == "test" ]; then
  echo "Running regular tests (excluding stress tests)"
  poetry run pytest
elif [ "$1" == "stress_test" ]; then
  echo "Running stress tests"
  if [ -z "$2" ]; then
    echo "Error: Please specify test duration: short, medium, long, or full"
    echo "Usage: ./run.sh stress_test [short|medium|long|full]"
    exit 1
  fi

  case "$2" in
    "short")
      echo "Running short stress test (60 seconds, 10 RPS)"
      poetry run python -m tests.stress.run_stress_test --scenario debug_test --max-duration 60 --target-rps 10
      ;;
    "medium")
      echo "Running medium stress test (300 seconds, 20 RPS)"
      poetry run python -m tests.stress.run_stress_test --scenario medium_test --max-duration 300 --target-rps 20
      ;;
    "long")
      echo "Running long stress test (600 seconds, 30 RPS)"
      poetry run python -m tests.stress.run_stress_test --scenario long_test --max-duration 600 --target-rps 30
      ;;
    "full")
      echo "Running full stress test (24 hours, 10 RPS, 100M tokens)"
      poetry run python -m tests.stress.run_stress_test --scenario 24h_stress_test --max-duration 86400 --target-rps 10
      ;;
    *)
      echo "Error: Invalid duration. Please use: short, medium, long, or full"
      exit 1
      ;;
  esac
elif [ "$1" == "build" ]; then
  echo "Running docker build"
  docker buildx build -f local.dockerfile . -t agentic_inventory:latest
elif [ "$1" == "run" ]; then
  echo "Running docker run"
  docker run --env-file .env -it -p 8080:8080 -v ${HOME}/.azure:/root/.azure:rw agentic_inventory:latest
elif [ "$1" == "check" ]; then
  echo "Running pre-commit checks..."
  pre-commit run --all-files
else
  echo "Invalid argument."
  exit 1
fi
