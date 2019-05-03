import pytest

from cabbage import exceptions, jobs, tasks, testing, worker


@pytest.fixture
def job_store():
    return testing.InMemoryJobStore()


@pytest.fixture
def task_manager(job_store):
    return tasks.TaskManager(job_store=job_store)


@pytest.fixture
def job_factory(job_store):
    defaults = {
        "id": 42,
        "task_name": "bla",
        "task_kwargs": {},
        "lock": None,
        "queue": "queue",
        "job_store": job_store,
    }

    def factory(**kwargs):
        final_kwargs = defaults.copy()
        final_kwargs.update(kwargs)
        return jobs.Job(**final_kwargs)

    return factory


def test_run(task_manager, mocker):
    class TestWorker(worker.Worker):
        i = 0

        def process_jobs(self):
            if self.i == 2:
                self.stop(None, None)
            self.i += 1

    test_worker = TestWorker(task_manager=task_manager, queue="marsupilami")

    test_worker.run(timeout=42)

    task_manager.job_store.listening_queues == {"marsupilami"}
    task_manager.job_store.waited == [42]


def test_process_jobs(mocker, task_manager, job_factory):
    job_1 = job_factory(id=42)
    job_2 = job_factory(id=43)
    job_3 = job_factory(id=44)
    task_manager.job_store.jobs["queue"] = [job_1, job_2, job_3]

    test_worker = worker.Worker(task_manager, "queue")

    i = 0

    def side_effect(job):
        nonlocal i
        i += 1
        if i == 1:
            # First time the task runs
            return None
        elif i == 2:
            # Then the task fails
            raise exceptions.JobError()
        else:
            # While the third task runs, a stop signal is received
            test_worker.stop(None, None)

    run_job = mocker.patch("cabbage.worker.Worker.run_job", side_effect=side_effect)

    test_worker.process_jobs()

    assert run_job.call_args_list == [
        mocker.call(job=job_1),
        mocker.call(job=job_2),
        mocker.call(job=job_3),
    ]

    assert task_manager.job_store.finished_jobs == [
        (job_1, jobs.Status.DONE),
        (job_2, jobs.Status.ERROR),
        (job_3, jobs.Status.DONE),
    ]


def test_process_jobs_until_no_more_jobs(mocker, task_manager, job_factory):
    job = job_factory(id=42)
    task_manager.job_store.jobs["queue"] = [job]

    mocker.patch("cabbage.worker.Worker.run_job")

    test_worker = worker.Worker(task_manager, "queue")
    test_worker.process_jobs()

    assert task_manager.job_store.finished_jobs == [(job, jobs.Status.DONE)]


def test_run_job(task_manager, job_store):
    result = []

    def task_func(a, b):  # pylint: disable=unused-argument
        result.append(a + b)

    task = tasks.Task(task_func, manager=task_manager, queue="yay", name="job")

    task_manager.tasks = {"task_func": task}

    job = jobs.Job(
        id=16,
        task_kwargs={"a": 9, "b": 3},
        lock="sherlock",
        task_name="task_func",
        queue="yay",
        job_store=job_store,
    )
    test_worker = worker.Worker(task_manager, "yay")
    test_worker.run_job(job)

    assert result == [12]


def test_run_job_error(task_manager, job_store):
    def job(a, b):  # pylint: disable=unused-argument
        raise ValueError("nope")

    task = tasks.Task(job, manager=task_manager, queue="yay", name="job")
    task.func = job

    task_manager.tasks = {"job": task}

    job = jobs.Job(
        id=16,
        task_kwargs={"a": 9, "b": 3},
        lock="sherlock",
        task_name="job",
        queue="yay",
        job_store=job_store,
    )
    test_worker = worker.Worker(task_manager, "yay")
    with pytest.raises(exceptions.JobError):
        test_worker.run_job(job)


def test_run_job_not_found(task_manager, job_store):
    job = jobs.Job(
        id=16,
        task_kwargs={"a": 9, "b": 3},
        lock="sherlock",
        task_name="job",
        queue="yay",
        job_store=job_store,
    )
    test_worker = worker.Worker(task_manager, "yay")
    with pytest.raises(exceptions.TaskNotFound):
        test_worker.run_job(job)