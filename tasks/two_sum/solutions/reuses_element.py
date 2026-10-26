def two_sum(nums, target):
    # Bug: the inner loop starts at i, so an element can pair with itself.
    for i in range(len(nums)):
        for j in range(i, len(nums)):
            if nums[i] + nums[j] == target:
                return [i, j]
    raise ValueError("no two numbers add to target")
