"""Data onboarding for the million songs dataset with Docker, SQLAlchemy and Postgres."""
import logging

from python_on_whales import docker
from sqlalchemy import create_engine, inspect

from etl import run_initial_pipeline
from tables import metadata

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":

    # Check that container is running
    container_names = [container.name for container in docker.ps()]
    if "sparkify" in container_names:

        engine = create_engine(
            "postgresql+psycopg2://postgres:postgres@localhost:6543/sparkifydb", future=True
        )

        logging.info("Engine created.")

        # Create schema if necessary
        inspector = inspect(engine)
        if not all([tbl in inspector.get_table_names() for tbl in ["artists_init", "songs_init"]]):
            with engine.begin() as conn:
                metadata.create_all(conn)
            logging.info("Schema created.")
        else:
            logging.info("Schema already exists.")

        # Initial pipeline
        run_initial_pipeline(engine)
        logging.info("Initial ETL pipeline successfully run.")

        engine.dispose()

        logging.warning("Make sure to shut down the Postgres container.")

    else:
        logging.error("No Postgres container running.")
