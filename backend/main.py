# backend/main.py
import os

# ✅ 关键：优先加载 .env（必须在导入 auth_router 之前）
try:
    from dotenv import load_dotenv

    # 默认读取当前工作目录下的 .env；
    # 为了更稳，也可以显式指定 main.py 同级 .env 路径
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    # 没装 python-dotenv 也不影响启动，只是读不到 .env
    pass

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy.orm import Session

from database import SessionLocal, Base, engine
from models import Device

from digest_database import digest_engine, DigestBase
from digest_models import DailyDigest  # 确保模型被 import，表才会注册到 metadata

# ✅ 在加载 .env 之后再导入会读取环境变量的模块/路由
from auth import router as auth_router
from routers.projects import router as projects_router
from routers.notes import router as notes_router
from routers.files import router as files_router
from routers.vasp import router as vasp_router
from routers.vasp_stats import router as vasp_stats_router
from routers.vasp_db import router as vasp_db_router      
from routers.changelog import router as changelog_router  # 新增日志路由
from routers.issues import router as issues_router # 新增反馈路由
from routers.qe_epw_db import router as qe_epw_db_router
from routers.academic_reports import router as academic_reports_router  # 新增学术报告
from routers.dailypapers import router as dailypapers_router # 新增每日文献路由
from routers.server_monitor import router as server_monitor_router
from routers.agents import router as agents_router
from routers.papers_library import router as papers_library_router # 新增论文库路由
from routers.health import router as health_router
from route_integrity import assert_unique_routes

def create_tables():
    """
    ✅ 根据 models.py 创建所有表
    适合：你现在“删库后重建”这种场景
    注意：它不会自动做复杂迁移（改字段/改约束的增量迁移），那是 Alembic 的工作
    """
    Base.metadata.create_all(bind=engine)


def init_devices():
    db: Session = SessionLocal()
    try:
        if db.query(Device).count() == 0:
            d1 = Device(name="PPMS-9", location="低温实验室", description="物性测量系统")
            d2 = Device(name="XRD", location="材料实验室", description="X射线衍射仪")
            db.add_all([d1, d2])
            db.commit()
    finally:
        db.close()


is_prod = os.getenv("ENV", "prod").lower() == "prod"
# 生产默认关闭；你也可以用 ENABLE_DOCS=1 临时打开
enable_docs = os.getenv("ENABLE_DOCS", "0") == "1"

app = FastAPI(
    title="ELN Backend (Python)",
    openapi_url=None if (is_prod and not enable_docs) else "/api/openapi.json",
    docs_url=None if (is_prod and not enable_docs) else "/api/docs",
    redoc_url=None if (is_prod and not enable_docs) else "/api/redoc",
)

# 跨域设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://matflow.top",
        "http://222.195.94.37:5173",
        "http://222.195.94.37",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件：上传目录
from pathlib import Path

DATA_DIR = Path(os.getenv("LMATELAB_DATA_DIR", "/app/var")).resolve()
UPLOADS_DIR = Path(os.getenv("UPLOADS_ROOT", str(DATA_DIR / "uploads"))).resolve()

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# 注册路由
api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(notes_router)
api_router.include_router(files_router)
api_router.include_router(vasp_router)
api_router.include_router(vasp_stats_router)
api_router.include_router(vasp_db_router)
api_router.include_router(changelog_router)  # 注册日志路由
api_router.include_router(issues_router) # 注册反馈路由
api_router.include_router(qe_epw_db_router) # 注册qe_epw数据库路由
api_router.include_router(academic_reports_router) # 注册学术报告路由
api_router.include_router(dailypapers_router) # 注册每日文献路由
api_router.include_router(server_monitor_router) # 服务器信息统计
api_router.include_router(agents_router) # agent
api_router.include_router(papers_library_router) # 注册论文库路由
api_router.include_router(health_router)

app.include_router(api_router)
assert_unique_routes(app)

@app.on_event("startup")
def on_startup():
    
    auto_create = os.getenv("AUTO_CREATE_TABLES", "0") == "1"
    auto_seed = os.getenv("AUTO_SEED_DEVICES", "0") == "1"

    if auto_create:
        create_tables()

    if auto_seed:
        init_devices()
