async def first(items):
    async for item in items:
        return item
    else:
        raise LookupError("empty")
