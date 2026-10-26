def two_sum(nums, target):
    # Bug: returns None instead of raising when there is no answer.
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                return [i, j]
    return None
