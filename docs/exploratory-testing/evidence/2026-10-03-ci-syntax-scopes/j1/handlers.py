# messpy-disable-next-line ShortVariable
def handle_request(req, urgent: bool = False):
    x = 1
    # messpy-disable-next-line DevelopmentCodeFragment
    # TODO: fix this
    # FIXME: check urgently
    data = {1: 'a', 1: 'b'}
    if req:
        return True
    else:
        return False
