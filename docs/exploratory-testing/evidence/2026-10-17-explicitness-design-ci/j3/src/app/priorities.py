def always_exiting_try(value):
    if value:
        try:
            return int(value)
        except ValueError:
            return 0
        else:
            return 1
    else:
        return -1

def build(customer_name_that_is_far_too_descriptive):
    # TODO: marker
    return customer_name_that_is_far_too_descriptive
