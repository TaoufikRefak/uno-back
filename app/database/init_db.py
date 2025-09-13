from app.database.models import Base  # wherever you declared Base = declarative_base()
from app.database.database import engine  # your async engine

async def init_db():
    async with engine.begin() as conn:
        # run the schema creation
        await conn.run_sync(Base.metadata.create_all)