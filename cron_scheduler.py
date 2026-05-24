import asyncio
from datetime import datetime, timezone
from croniter import croniter
from astrbot.api import logger


class CronScheduler:
    def __init__(self, cron_expression: str, timezone_obj=None):
        """
        Initialize the scheduler with a cron expression.

        Args:
            cron_expression: Standard cron expression (e.g., "*/5 * * * *")
            timezone_obj: Optional timezone object
        """
        self.cron_expression = cron_expression
        self.timezone = timezone_obj or timezone.utc
        self._task = None
        self._running = False

    def _get_base_time(self):
        """Get current time in the configured timezone."""
        return datetime.now(self.timezone)

    def get_next_run_time(self, from_time=None):
        """Calculate the next run time based on cron expression."""
        if from_time is None:
            from_time = self._get_base_time()

        cron = croniter(self.cron_expression, from_time)
        return cron.get_next(datetime)

    def get_prev_run_time(self, from_time=None):
        """Get the previous run time (useful for catching up)."""
        if from_time is None:
            from_time = self._get_base_time()

        cron = croniter(self.cron_expression, from_time)
        return cron.get_prev(datetime)

    async def _run_job(self, job_func, scheduled_time, *args, **kwargs):
        """Execute the job with timing information."""
        actual_time = datetime.now(self.timezone)
        delay = (actual_time - scheduled_time).total_seconds()

        if delay > 1:  # More than 1 second late
            logger.warning(
                f"Job running late by {delay:.2f} seconds. "
                f"Scheduled: {scheduled_time}, Actual: {actual_time}"
            )

        try:
            logger.info(f"Executing job scheduled for {scheduled_time}")
            result = await job_func(scheduled_time, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"Job failed: {e}")
            raise

    async def start(self, job_func, catch_up=True, *args, **kwargs):
        """
        Start the scheduler.

        Args:
            job_func: Async function to execute
            catch_up: If True, run missed executions immediately
            *args, **kwargs: Arguments to pass to job_func
        """
        self._running = True
        last_run = None

        while self._running:
            try:
                now = self._get_base_time()

                # Check if we need to catch up on missed executions
                if catch_up and last_run is not None:
                    # Find all missed run times between last_run and now
                    missed_runs = []
                    check_time = last_run

                    while True:
                        next_run = self.get_next_run_time(check_time)
                        if next_run > now:
                            break
                        missed_runs.append(next_run)
                        check_time = next_run

                    # Execute missed runs
                    if missed_runs:
                        logger.info(f"Found {len(missed_runs)} missed execution(s)")
                        for missed_time in missed_runs:
                            await self._run_job(job_func, missed_time, *args, **kwargs)

                # Calculate next run time
                next_run = self.get_next_run_time(now)
                wait_seconds = (next_run - now).total_seconds()

                if wait_seconds > 0:
                    logger.info(f"Next run scheduled at {next_run} (in {wait_seconds:.1f} seconds)")
                    await asyncio.sleep(wait_seconds)

                while True:
                    try:
                        # Execute the job
                        await self._run_job(job_func, next_run, *args, **kwargs)
                        last_run = next_run
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(f"Job failed: {e}. Retrying in 10s.")
                        await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Job failed: {e}. Retrying in 10s.")
                await asyncio.sleep(10)

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
