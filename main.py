import asyncio
import logging
from concurrent import futures

import grpc
import uvicorn

from app.config import Config
from app.grpc_servicer import AnalysisServicer
from app.analyze_servicer import AnalyzeServicer
from app.generated import analysis_pb2_grpc, dataanalysis_v1_pb2_grpc
from app.http_app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("main")


async def _serve_grpc() -> None:
    server = grpc.aio.server(
        migration_thread_pool=futures.ThreadPoolExecutor(max_workers=Config.GRPC_MAX_WORKERS),
        options=[
            ("grpc.max_receive_message_length", 16 * 1024 * 1024),  # 16 MB
            ("grpc.max_send_message_length", 16 * 1024 * 1024),
        ],
    )
    analysis_pb2_grpc.add_AnalysisServiceServicer_to_server(AnalysisServicer(), server)
    dataanalysis_v1_pb2_grpc.add_AnalysisServiceServicer_to_server(AnalyzeServicer(), server)
    listen_addr = f"[::]:{Config.GRPC_PORT}"
    server.add_insecure_port(listen_addr)
    await server.start()
    logger.info("gRPC server listening on %s", listen_addr)
    await server.wait_for_termination()


async def _serve_http() -> None:
    app = create_app()
    config = uvicorn.Config(
        app,
        host=Config.HTTP_HOST,
        port=Config.HTTP_PORT,
        log_config=None,
    )
    server = uvicorn.Server(config)
    logger.info("HTTP server listening on %s:%s", Config.HTTP_HOST, Config.HTTP_PORT)
    await server.serve()


async def main() -> None:
    await asyncio.gather(_serve_grpc(), _serve_http())


if __name__ == "__main__":
    asyncio.run(main())
