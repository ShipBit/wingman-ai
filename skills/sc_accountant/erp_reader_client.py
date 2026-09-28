"""Versioned, read-only durable event feed for local downstream consumers.

This module deliberately has no dependency on the reader service or monitor.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

CONTRACT_VERSION = 1
MAX_PAGE_SIZE = 1000


class FeedError(RuntimeError):
    """The database cannot safely satisfy the durable feed contract."""


class ReaderFeed:
    def __init__(self, path):
        self.path = Path(path)

    def read_page(self, after=0, limit=200):
        """Read one committed snapshot, ordered by insertion sequence, across environments.

        Consumers must persist source_id alongside next_cursor and reject a changed
        source identity before applying a page. Timestamps are never cursors.
        """
        if type(after) is not int or after < 0:
            raise ValueError('after must be a nonnegative integer')
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f'limit must be an integer between 1 and {MAX_PAGE_SIZE}')
        try:
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        except sqlite3.Error as exc:
            raise FeedError(f'Cannot open reader database: {exc}') from exc
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            try:
                metadata = dict(db.execute(
                    "SELECT key,value FROM metadata WHERE key IN ('erp_feed_source_id','erp_feed_contract_version')"))
            except sqlite3.Error as exc:
                raise FeedError('Reader feed is not initialized; start the updated reader service first') from exc
            source_id = metadata.get('erp_feed_source_id')
            version = metadata.get('erp_feed_contract_version')
            if not source_id or version is None:
                raise FeedError('Reader feed is not initialized; start the updated reader service first')
            if version != str(CONTRACT_VERSION):
                raise FeedError(f'Unsupported reader feed contract version: {version}')
            high_water = db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            if after > high_water:
                raise FeedError('Cursor is ahead of reader database; reconcile a restored or replaced source')
            rows = db.execute(
                '''SELECT e.id,e.occurrence,e.environment,e.payload,
                          o.generation,o.byte_start,o.byte_end,o.source_timestamp,o.instruction_version,o.rule_id
                   FROM events e LEFT JOIN observations o ON o.occurrence=e.occurrence
                   WHERE e.id>? AND e.id<=? ORDER BY e.id ASC LIMIT ?''',
                (after, high_water, limit + 1)).fetchall()
            events = []
            for row in rows[:limit]:
                sequence, occurrence, environment, payload, generation, start, end, timestamp, instructions, rule = row
                event = json.loads(payload)
                if not isinstance(event, dict):
                    raise FeedError(f'Invalid event payload at sequence {sequence}')
                event.update(
                    id=f'{source_id}:{sequence}', sequence=sequence,
                    source_occurrence=occurrence, environment=environment,
                    source={'occurrence': occurrence, 'generation': generation,
                            'byte_start': start, 'byte_end': end,
                            'source_timestamp': timestamp, 'instruction_version': instructions,
                            'rule_id': rule})
                events.append(event)
            return {
                'contract_version': CONTRACT_VERSION, 'source_id': source_id,
                'after': after, 'next_cursor': events[-1]['sequence'] if events else after,
                'has_more': len(rows) > limit, 'events': events,
                'health': {'snapshot_high_water': high_water,
                           'reader_live_status': 'not_observed',
                           'scope': 'Committed database snapshot; does not establish game or monitor activity'},
            }
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise FeedError(f'Cannot read compatible reader feed: {exc}') from exc
        finally:
            db.close()
