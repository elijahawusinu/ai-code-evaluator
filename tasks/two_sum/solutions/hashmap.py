def two_sum(nums, target):
    seen = {}
    for j, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], j]
        seen[n] = j
    raise ValueError("no two numbers add to target")
