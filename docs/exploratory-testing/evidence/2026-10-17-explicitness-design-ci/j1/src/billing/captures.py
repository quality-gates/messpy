"""Captured storage read through a helper, as the explicitness contract describes."""

SHARED = [1]


def direct_capture():
    def reader():
        return SHARED[0]

    return reader()


def through_helper():
    def helper():
        return SHARED[0]

    def through():
        return helper()

    return through()


def parameter_through_helper(box):
    def helper():
        return box[0]

    def through():
        return helper()

    return through()


def private_capture():
    box = [1]

    def reader():
        return box[0]

    return reader()


def escaped_capture():
    box = [1]

    def reader():
        return box[0]

    return reader
