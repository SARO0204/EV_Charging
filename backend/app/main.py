from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.chargers import router as chargers_router
from .api.dashboard import router as dashboard_router
from .api.ev import router as ev_router
from .api.queue import router as queue_router
from .api.reservations import router as reservations_router
from .api.simulation import router as simulation_router
from .services.data_service import (
    InvalidDocumentIdError,
    MalformedFirestoreDocumentError,
)
from .services.data_errors import (
    FirebaseConfigurationError,
    FirestoreReadError,
	FirestoreWriteError,
)
from .services.data_provider import DataProviderConfigurationError
from .services.demo_data_provider import DemoDataConfigurationError
from .services.queue_prediction_service import InsufficientQueuePredictionDataError
from .services.grid_intelligence_service import InvalidGridDataError

app = FastAPI(title="GridFlow AI")
app.include_router(ev_router)
app.include_router(chargers_router)
app.include_router(queue_router)
app.include_router(reservations_router)
app.include_router(simulation_router)
app.include_router(dashboard_router)


@app.exception_handler(InvalidDocumentIdError)
async def invalid_document_id_handler(
	request: Request, exc: InvalidDocumentIdError
):
	return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(FirebaseConfigurationError)
async def firebase_configuration_error_handler(
	request: Request, exc: FirebaseConfigurationError
):
	return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(DataProviderConfigurationError)
async def data_provider_configuration_error_handler(
	request: Request, exc: DataProviderConfigurationError
):
	return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(DemoDataConfigurationError)
async def demo_data_configuration_error_handler(
	request: Request, exc: DemoDataConfigurationError
):
	return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(FirestoreReadError)
async def firestore_read_error_handler(request: Request, exc: FirestoreReadError):
	return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(FirestoreWriteError)
async def firestore_write_error_handler(request: Request, exc: FirestoreWriteError):
	return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(MalformedFirestoreDocumentError)
async def malformed_document_handler(
	request: Request, exc: MalformedFirestoreDocumentError
):
	return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(InsufficientQueuePredictionDataError)
async def insufficient_queue_data_handler(
	request: Request, exc: InsufficientQueuePredictionDataError
):
	return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(InvalidGridDataError)
async def invalid_grid_data_handler(request: Request, exc: InvalidGridDataError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})