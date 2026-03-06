from sqlalchemy.orm import Session


class BaseSeeder:
    def __init__(self, db: Session):
        self.db = db

    def run(self):
        raise NotImplementedError("")

    def log(self, message: str):
        print(f"  {message}")