# models/payment_transaction_mapping.py
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from db.extensions import db

class PaymentTransactionMapping(db.Model):
    __tablename__ = 'payment_transaction_mappings'

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, nullable=False)
    transaction_id = Column(Integer, nullable=False)
    payment_id = Column(String(100), nullable=False)

    def __repr__(self):
        return f"<PaymentTransactionMapping booking_id={self.booking_id} transaction_id={self.transaction_id} payment_id={self.payment_id}>"
