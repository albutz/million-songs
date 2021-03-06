"""ETL pipeline."""
import logging
from pathlib import Path

from sqlalchemy import Column, select, text
from sqlalchemy.engine import Result
from sqlalchemy.future.engine import Engine

from read import get_file_paths, read_h5
from utils import cast_numeric, encode_str


class Pipeline:
    """ETL process."""

    def __init__(self, engine: Engine, tables: dict) -> None:
        """Initialize pipline.

        Args:
            engine: Engine to connect to.
            tables: Dictionary with table objects.
        """
        self.engine = engine
        self.tables = tables

    def _execute(self, stmt: str | text) -> Result:
        """Run a query.

        Args:
            stmt: Query to run.

        Returns:
            Result of the query.
        """
        with self.engine.connect() as conn:
            res = conn.execute(stmt)
        return res

    def _commit(self, stmt: str | text) -> None:
        """Run a query and commit it.

        Args:
            stmt: Query to run.
        """
        with self.engine.connect() as conn:
            conn.execute(stmt)
            conn.commit()

    def run(self) -> None:
        """Complete ETL pipeline.

        - Extract flat files, perform minimal transformations and load into intermediary tables
        - Insert into artists table
        - Insert into locations table
        - Create many-to-many mapping for artists and locations
        - Insert into songs table
        - Drop intermediary tables
        """
        self.run_initial_pipeline()
        self.run_artist_pipeline()
        self.run_location_pipeline()
        self.run_artist_location_pipeline()
        self.run_album_pipeline()
        self.run_song_pipeline()
        self.drop_init_tables()

    def run_initial_pipeline(self) -> None:
        """Initial ETL pipeline.

        Minimal processing to load songs and artists into the database.
        """
        logging.info("Starting initial pipeline...")

        file_paths = get_file_paths(Path("data"))

        for file_path in file_paths:

            # Load individual file
            song_df = read_h5(file_path)

            # Insert artist
            # fmt: off
            insert_artist_stmt = (
                self.tables["artists_init"].
                insert().
                values(
                    name=encode_str(song_df.artist_name),
                    location=encode_str(song_df.artist_location),
                    latitude=cast_numeric(song_df.artist_latitude),
                    longitude=cast_numeric(song_df.artist_longitude)
                )
            )
            # fmt: on

            self._commit(insert_artist_stmt)

            # Insert song
            # fmt:off
            insert_song_stmt = (
                self.tables["songs_init"].
                insert().
                values(
                    title=encode_str(song_df.title),
                    year=cast_numeric(song_df.year),
                    danceability=cast_numeric(song_df.danceability),
                    duration=cast_numeric(song_df.duration),
                    end_of_fade_in=cast_numeric(song_df.end_of_fade_in),
                    start_of_fade_out=cast_numeric(song_df.start_of_fade_out),
                    loudness=cast_numeric(song_df.loudness),
                    bpm=cast_numeric(song_df.tempo),
                    album_name=encode_str(song_df.release),
                    artist_name=encode_str(song_df.artist_name),
                )
            )
            # fmt: on

            self._commit(insert_song_stmt)

        logging.info("Initial ETL pipeline successfully run!")

    def run_artist_pipeline(self) -> None:
        """Insert into artists table."""
        stmt = text(
            """
            INSERT INTO artists (name)
            SELECT DISTINCT name
            FROM artists_init
            WHERE name IS NOT NULL;
            """
        )

        self._commit(stmt)

        logging.info("Artists table cleaned!")

    def run_location_pipeline(self) -> None:
        """Insert into locations table."""
        logging.info("Starting pipeline to clean locations table...")

        stmt = select(self.tables["artists_init"].c.location.distinct())

        res = self._execute(stmt)

        locations = [row[0] for row in res.all()]

        def get_lng_lat_val(col: Column, location: str) -> list | None:
            """Helper to insert unique latitude and longitude values only.

            Args:
                col: Column object for latitude or longitude
                location: Single location as a string

            Returns:
                Latitude or longitude value if it is unique for a location and else None.
            """
            stmt = select(col).where(self.tables["artists_init"].c.location == location)

            res = self._execute(stmt)

            val = [row[0] for row in res.all()]
            val = list(set(val))
            insert_val = val[0] if len(val) == 1 else None

            return insert_val

        for location in locations:

            if location is None:
                continue

            lat = get_lng_lat_val(self.tables["artists_init"].c.latitude, location)
            lng = get_lng_lat_val(self.tables["artists_init"].c.longitude, location)

            insert_loc_stmt = (
                self.tables["locations"]
                .insert()
                .values(name=location, latitude=lat, longitude=lng)
            )

            self._commit(insert_loc_stmt)

        logging.info("Locations table cleaned!")

    def run_artist_location_pipeline(self) -> None:
        """Many-to-many relationship table for artists and locations."""
        logging.info(
            "Starting pipeline for many-to-many mapping of artists and locations."
        )

        artist_stmt = select(self.tables["artists"].c.id, self.tables["artists"].c.name)

        res = self._execute(artist_stmt)

        artist_names = res.all()

        for artist_id, artist_name in artist_names:

            # Get the location of that artist
            loc_stmt = select(self.tables["artists_init"].c.location).where(
                self.tables["artists_init"].c.name == artist_name
            )

            self._execute(loc_stmt)

            loc = list(set(res.all()))
            loc_val = loc[0][0] if len(loc) == 1 else None

            if loc_val is None:
                continue

            loc_id_stmt = select(self.tables["locations"].c.id).where(
                self.tables["locations"].c.name == loc_val
            )

            self._execute(loc_id_stmt)

            location_id = res.scalar()

            insert_stmt = (
                self.tables["artists_locations"]
                .insert()
                .values(artist_id=artist_id, location_id=location_id)
            )

            self._commit(insert_stmt)

        logging.info("Mapping table finished!")

    def run_album_pipeline(self) -> None:
        """Insert into albums table."""
        logging.info("Starting pipeline to clean albums table...")

        stmt = text(
            """
            INSERT INTO albums (title, artist_id)
            SELECT DISTINCT album_name, (SELECT id FROM artists AS a WHERE a.name = s.artist_name)
            FROM songs_init AS s;
            """
        )

        self._commit(stmt)

        logging.info("Album table cleaned!")

    def run_song_pipeline(self) -> None:
        """Insert into songs table."""
        stmt = text(
            """
            INSERT INTO songs (
                title,
                year,
                danceability,
                duration,
                end_of_fade_in,
                start_of_fade_out,
                loudness,
                bpm,
                album_id,
                artist_id
            )
            SELECT
                title,
                year,
                danceability,
                duration,
                end_of_fade_in,
                start_of_fade_out,
                loudness,
                bpm,
                (
                    SELECT id
                    FROM albums
                    WHERE (albums.title = s.album_name) AND (
                        (SELECT name FROM artists WHERE artists.id = albums.artist_id)
                        = s.artist_name
                    )
                ),
                (
                    SELECT id
                    FROM artists
                    WHERE artists.name = s.artist_name
                )
            FROM songs_init AS s
            """
        )

        self._commit(stmt)

        logging.info("Songs table cleaned!")

    def drop_init_tables(self) -> None:
        """Drop initial tables."""
        init_tables = [
            tbl_name for tbl_name in self.tables.keys() if "init" in tbl_name
        ]
        stmts = [text(f"DROP TABLE {tbl}") for tbl in init_tables]

        for stmt in stmts:
            self._commit(stmt)

        logging.info("Initial tables dropped.")
