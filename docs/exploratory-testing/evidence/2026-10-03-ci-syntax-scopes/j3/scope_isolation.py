def outer_service(multiplier: int):
    items = [1, 2, 3]

    def helper(items):
        return [x * multiplier for x in items]

    return helper(items)

def process_matrix():
    matrix = [[1, 2], [3, 4]]
    sums = [1 for row in matrix for col in row]
    collected = [v for row in matrix if (v := len(row)) > 1]
    return sums, collected, v
