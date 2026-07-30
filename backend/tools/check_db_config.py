import asyncio
from sqlalchemy import select
from database.connection import async_session
from models.data_feed_config import DataFeedConfig
from config.settings import settings

async def main():
    print("Database URL:", settings.DATABASE_URL)
    async with async_session() as session:
        stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
        res = await session.execute(stmt)
        config = res.scalar_one_or_none()
        if config:
            print("Config ID:", config.id)
            print("API Key (Client ID):", config.api_key)
            print("API Secret (decrypted):", config.get_api_secret())
            print("Base URL:", config.base_url)
            print("Is Enabled:", config.is_enabled)
            print("Connection Status:", config.connection_status)
            print("Error Message:", config.error_message)
        else:
            print("No DataFeedConfig found in database.")

if __name__ == "__main__":
    asyncio.run(main())
