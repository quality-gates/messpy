class Split:
    def touch_left(self, extra):
        self.left = extra
        return self.left + 1

    def touch_right(self, extra):
        self.right = extra
        return self.right + 1


class Together:
    def read(self, extra):
        return self.value + extra

    def write(self, value):
        self.value = value
        return self.read(0)
