from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from passlib.apps import custom_app_context as pwd_context
import random, string

Base = declarative_base()

class User(Base):
    __tablename__ = 'user'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    email = Column(String(200))
    password_hash = Column(String(64))
    is_authenticated = Column(Boolean)
    is_active = Column(Boolean)

    def hash_password(self, password):
        self.password_hash = pwd_context.encrypt(password)

    def verify_password(self, password):
        return pwd_context.verify(password, self.password_hash)

    def get_id(self):
        return unicode(self.id)

    @property
    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'hash': self.password_hash,
        }


class Category(Base):
    __tablename__ = 'category'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship(User)

    @property
    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'creator': self.user_id,
        }


class Item(Base):
    __tablename__ = 'item'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(String(500))
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship(User)
    cat_name = Column(Integer, ForeignKey('category.name'))
    category = relationship(Category)

    @property
    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'creator': self.user_id,
            'category': self.cat_name,
        }



engine = create_engine('postgresql://catalog:database@localhost/catalogdb')
Base.metadata.create_all(engine)
