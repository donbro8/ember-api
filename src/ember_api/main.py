import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ember_shared import setup_logging, settings
from .routes import health, query as query_router, results as results_router, watches as watches_router

setup_logging(level=settings.LOG_LEVEL, json_format=settings.LOG_JSON_FORMAT)

logger = logging.getLogger(__name__)


def _build_ember_agent():  # noqa: C901
    """Construct EmberAgent with all dependencies.

    Returns the agent on success.  Returns None if a critical dependency is
    unavailable, logging a warning so the API starts in degraded mode.
    """
    try:
        from ember_agents.agent import EmberAgent
        from ember_agents.search.interpret import IntentExtractor
        from ember_agents.search.classify import ClassificationOrchestrator
        from ember_agents.search.gate import SearchGate
        from ember_agents.search.fetch import FetchOrchestrator
        from ember_agents.search.match import MatchScorer
        from ember_agents.search.seed_source import BiologicSeedSource
    except ImportError as exc:
        logger.warning("ember-agents not available — running in degraded mode: %s", exc)
        return None

    # --- resolvers (from ember-data) ---
    try:
        from ember_data.classification.atc_resolver import ATCResolver
        from ember_data.classification.mesh_resolver import MeSHResolver
        from ember_data.classification.uniprot_resolver import UniProtResolver
        from ember_data.classification.modality_resolver import ModalityResolver

        atc_resolver = ATCResolver()
        mesh_resolver = MeSHResolver()
        uniprot_resolver = UniProtResolver()
        modality_resolver = ModalityResolver()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resolver construction failed — running in degraded mode: %s", exc)
        return None

    # --- IntentExtractor ---
    try:
        intent_extractor = IntentExtractor()
    except Exception as exc:  # noqa: BLE001
        logger.warning("IntentExtractor unavailable — running in degraded mode: %s", exc)
        return None

    # --- ClassificationOrchestrator ---
    try:
        classifier = ClassificationOrchestrator(
            uniprot_resolver=uniprot_resolver,
            modality_resolver=modality_resolver,
            mesh_resolver=mesh_resolver,
            atc_resolver=atc_resolver,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ClassificationOrchestrator unavailable — running in degraded mode: %s", exc)
        return None

    # --- SearchGate ---
    try:
        class _NullEstimator:
            async def estimate(self, spec) -> int:
                return 0

        class _NullNarrowingProvider:
            async def get_options(self, dimension, spec) -> list:
                return []

        gate = SearchGate(
            estimator=_NullEstimator(),
            narrowing_provider=_NullNarrowingProvider(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SearchGate unavailable — running in degraded mode: %s", exc)
        return None

    # --- FetchOrchestrator ---
    try:
        bq_project = getattr(settings, "GCP_PROJECT_ID", None)
        fetcher = FetchOrchestrator(bq_project_id=bq_project)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FetchOrchestrator unavailable — running in degraded mode: %s", exc)
        return None

    # --- BiologicSeedSource ---
    try:
        import importlib.resources as pkg_resources
        import pathlib

        # Try to locate biologic_reference.json from ember_data package
        try:
            seed_ref = pkg_resources.files("ember_data.seed").joinpath("biologic_reference.json")
            seed_path = pathlib.Path(str(seed_ref))
        except Exception:  # noqa: BLE001
            seed_path = None

        if seed_path is None or not seed_path.exists():
            logger.warning("biologic_reference.json not found — BiologicSeedSource unavailable")
            return None

        seed_source = BiologicSeedSource(seed_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BiologicSeedSource unavailable — running in degraded mode: %s", exc)
        return None

    # --- MatchScorer ---
    try:
        scorer = MatchScorer(
            atc_resolver=atc_resolver,
            uniprot_resolver=uniprot_resolver,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MatchScorer unavailable — running in degraded mode: %s", exc)
        return None

    try:
        agent = EmberAgent(
            intent_extractor=intent_extractor,
            classifier=classifier,
            gate=gate,
            fetcher=fetcher,
            scorer=scorer,
            seed_source=seed_source,
        )
        logger.info("EmberAgent wired successfully")
        return agent
    except Exception as exc:  # noqa: BLE001
        logger.warning("EmberAgent construction failed — running in degraded mode: %s", exc)
        return None


def _build_result_store():
    """Construct ResultWriter and ResultReader instances.

    Returns (writer, reader, client, dataset) on success, or (None, None, None, None)
    if BigQuery is unavailable.
    """
    bq_project = getattr(settings, "GCP_PROJECT_ID", None)
    if not bq_project:
        logger.warning("GCP_PROJECT_ID not set — result store unavailable")
        return None, None, None, None

    try:
        from ember_data.bigquery.client import BigQueryClient
        from ember_data.bigquery.result_store import ResultWriter, ResultReader

        dataset = getattr(settings, "BQ_RESULTS_DATASET", "ember_results")
        client = BigQueryClient(project=bq_project)
        writer = ResultWriter(client=client, dataset=dataset)
        reader = ResultReader(client=client, dataset=dataset)
        logger.info("ResultWriter and ResultReader wired successfully")
        return writer, reader, client, dataset
    except ImportError as exc:
        logger.warning("ember-data result store not available — result persistence disabled: %s", exc)
        return None, None, None, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Result store construction failed — result persistence disabled: %s", exc)
        return None, None, None, None


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent = _build_ember_agent()
    if agent is None:
        logger.warning("EmberAgent unavailable — /query endpoint will return errors")
    app.state.ember_agent = agent

    result_writer, result_reader, bq_client, bq_dataset = _build_result_store()
    app.state.result_writer = result_writer
    app.state.result_reader = result_reader

    app.state.watch_store = None
    try:
        from ember_data.bigquery.watch_store import WatchStore

        if bq_client is not None:
            app.state.watch_store = WatchStore(bq_client, bq_dataset)
            logger.info("WatchStore wired successfully")
        else:
            logger.warning("WatchStore unavailable: BigQuery client not initialised")
    except Exception as exc:  # noqa: BLE001
        logger.warning("WatchStore unavailable: %s", exc)

    yield


app = FastAPI(title="Ember Bio API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(query_router.router)
app.include_router(results_router.router)
app.include_router(watches_router.router)
