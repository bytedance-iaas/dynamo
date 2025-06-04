import asyncio
import time

from deadline_aware_queue import DeadlineAwareRequestQueue


def ms_now():
    return int(time.time() * 1000)


async def test_basic_edf_ordering():
    print("\nRunning: test_basic_edf_ordering")
    queue = DeadlineAwareRequestQueue()

    now = ms_now()
    r1 = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 400}  # deadline = now + 100
    r2 = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 300}  # deadline = now + 200

    await queue.put(r2)
    await queue.put(r1)

    await asyncio.sleep(0.2)  # Give time for r1 to become eligible
    req = await queue.get_eligible(is_idle=False)
    assert req is r1
    print("Passed: test_basic_edf_ordering")


async def test_opportunistic_sjf():
    print("\nRunning: test_opportunistic_sjf")
    queue = DeadlineAwareRequestQueue()

    now = ms_now()
    r1 = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 300}
    r2 = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 200}

    await queue.put(r1)
    await queue.put(r2)

    req = await queue.get_eligible(is_idle=True)
    assert req in (r1, r2)
    print("Passed: test_opportunistic_sjf")


async def test_buffer_ms_behavior():
    print("\nRunning: test_buffer_ms_behavior")
    queue = DeadlineAwareRequestQueue(buffer_ms=50)

    now = ms_now()
    r = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 400}  # deadline = now + 100

    await queue.put(r)

    await asyncio.sleep(0.06)
    req = await queue.get_eligible(is_idle=False)
    assert req is r
    print("Passed: test_buffer_ms_behavior")


async def test_negative_buffer_rejected():
    print("\nRunning: test_negative_buffer_rejected")
    try:
        DeadlineAwareRequestQueue(buffer_ms=-1)
        raise AssertionError("Failed: negative buffer_ms was accepted")
    except ValueError:
        print("Passed: test_negative_buffer_rejected")


async def test_priority_by_slack_on_equal_deadline():
    print("\nRunning: test_priority_by_slack_on_equal_deadline")
    queue = DeadlineAwareRequestQueue()
    now = ms_now()

    r1 = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 200}  # slack = 300
    r2 = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 100}  # slack = 400

    await queue.put(r1)
    await queue.put(r2)

    await asyncio.sleep(0.2)
    req = await queue.get_eligible(is_idle=False)
    assert req is r1
    print("Passed: test_priority_by_slack_on_equal_deadline")


async def test_enforce_deadline_blocking():
    print("\nRunning: test_enforce_deadline_blocking")
    queue = DeadlineAwareRequestQueue()
    now = ms_now()

    r = {"arrival_time": now, "ttft": 500, "estimated_prefill_time": 400}  # deadline = now + 100
    await queue.put(r)

    try:
        # This test *expects* a timeout
        await asyncio.wait_for(queue.get_eligible(is_idle=False), timeout=0.03)
        raise AssertionError("Failed: request was dispatched too early")
    except asyncio.TimeoutError:
        print("Passed: test_enforce_deadline_blocking")


# Main runner
async def main():
    await test_basic_edf_ordering()
    await test_opportunistic_sjf()
    await test_buffer_ms_behavior()
    await test_negative_buffer_rejected()
    await test_priority_by_slack_on_equal_deadline()
    await test_enforce_deadline_blocking()


if __name__ == "__main__":
    asyncio.run(main())
