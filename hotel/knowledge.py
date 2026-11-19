"""Compatibility entry point for approved categorical hotel guidance."""

from hotel.extraction import extract
from hotel.procedures import select


def retrieve(db, hotel, query):
    return select(db, hotel, extract(query))["procedures"]
