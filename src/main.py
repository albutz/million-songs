"""Data onboarding for the million songs dataset with Docker, SQLAlchemy and Postgres."""
import logging

from python_on_whales import DockerClient
from sqlalchemy import create_engine

from setup import Docker

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":

    docker_client = DockerClient(compose_files=["docker-compose.yml"])

    with Docker(docker_client) as container:

        engine = create_engine(
            "postgresql+psycopg2://postgres:postgres@localhost:6543/sparkifydb",
            echo=True,
            future=True,
        )

        logging.info("Engine created.")