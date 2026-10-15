"""Tiny in-memory stand-in for motor collections, shared by the server tests."""
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError


class Col:
    """Supports equality, $gte, $in, $or filters; $set/$inc/upsert updates; optional unique field."""

    def __init__(self, unique=None):
        self.docs = []
        self.unique = unique

    @classmethod
    def _match(cls, d, q):
        for k, v in q.items():
            if k == "$or":
                if not any(cls._match(d, sub) for sub in v):
                    return False
            elif isinstance(v, dict):
                if "$gte" in v and not d.get(k, "") >= v["$gte"]:
                    return False
                if "$lt" in v and not d.get(k, "") < v["$lt"]:
                    return False
                if "$in" in v and d.get(k) not in v["$in"]:
                    return False
            elif d.get(k) != v:
                return False
        return True

    async def find_one(self, q, sort=None):
        hits = [d for d in self.docs if self._match(d, q)]
        if sort:
            hits.sort(key=lambda d: d.get(sort[0][0], ""), reverse=sort[0][1] < 0)
        return dict(hits[0]) if hits else None

    async def insert_one(self, d):
        if self.unique and any(x.get(self.unique) == d.get(self.unique) for x in self.docs):
            raise DuplicateKeyError("duplicate")
        self.docs.append(dict(d))

    async def delete_one(self, q):
        for d in self.docs:
            if self._match(d, q):
                self.docs.remove(d)
                return

    async def delete_many(self, q):
        self.docs = [d for d in self.docs if not self._match(d, q)]

    async def count_documents(self, q):
        return sum(1 for d in self.docs if self._match(d, q))

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(upd.get("$set", {}))
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                for k, v in upd.get("$addToSet", {}).items():
                    if v not in d.setdefault(k, []):
                        d[k].append(v)
                return SimpleNamespace(matched_count=1)
        if upsert:
            self.docs.append({**{k: v for k, v in q.items() if not k.startswith("$")}, **upd.get("$set", {})})
            return SimpleNamespace(matched_count=0)
        return SimpleNamespace(matched_count=0)

    async def find_one_and_update(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                before = dict(d)
                d.update(upd.get("$set", {}))
                for k, n in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + n
                return before
        if upsert:
            new = {k: v for k, v in q.items() if not k.startswith("$")}
            if "_id" in new and any(x.get("_id") == new["_id"] for x in self.docs):
                raise DuplicateKeyError("duplicate _id")   # what MongoDB does when the filter misses
            self.docs.append({**new, **upd.get("$set", {})})
        return None

    def find(self, q):
        outer = self

        class Cursor:
            async def to_list(self, n):
                return [dict(d) for d in outer.docs if outer._match(d, q)]
        return Cursor()
