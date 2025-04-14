from fastapi import APIRouter, HTTPException, Depends
from agentic_inventory.backend.models.job_model import JobStatus
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.backend.models.job_execution_model import JobExecutionModel
from agentic_inventory.utils.extensions import logger
from typing import List, Dict
from datetime import datetime
from agentic_inventory.backend.storage.storage_jobs import StorageJobsClient

router = APIRouter(prefix="/jobs", tags=["jobs"])


# Get Cosmos DB client
def get_storage():
    return StorageJobsClient()


@router.post("/{job_name}", response_model=dict, status_code=201)
async def create_job(job_name: str, config: JobConfig, storage=Depends(get_storage)):
    """Create a new job configuration"""
    try:
        # Check if job already exists
        existing_config = storage.get_job_config(job_name)
        if existing_config:
            raise HTTPException(status_code=400, detail=f"Job {job_name} already exists")

        # Set the job name
        config.job_name = job_name

        # Create the job config
        job_config = storage.create_job_config(config)

        return {"message": f"Job {job_name} created", "job": job_config.model_dump()}
    except Exception as e:
        logger.error(f"Failed to create job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create job")


@router.get("", response_model=List[Dict])
async def list_jobs(storage=Depends(get_storage)):
    """List all job configurations"""
    try:
        configs = storage.list_job_configs()
        return [config.model_dump() for config in configs]
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list jobs")


@router.get("/{job_name}")
async def describe_job(job_name: str, storage=Depends(get_storage)):
    """Get detailed information about a job including its configuration and execution history"""
    try:
        # Get job configuration
        job_config = storage.get_job_config(job_name)
        if not job_config:
            raise HTTPException(status_code=404, detail=f"Job {job_name} not found")

        # Get job execution history
        executions = storage.get_job_executions(job_name=job_name)

        # Format the response
        response = {
            "job_info": {
                "job_name": job_name,
                "config": job_config.model_dump(),
            },
            "execution_history": [
                {
                    "id": execution.id,
                    "status": execution.status,
                    "result": execution.result,
                    "started_at": execution.createdAt,
                    "completed_at": execution.updatedAt,
                }
                for execution in executions
            ],
            "summary": {
                "total_executions": len(executions),
                "last_execution": executions[0].updatedAt if executions else None,
                "last_status": executions[0].status if executions else None,
            },
        }

        return response

    except Exception as e:
        logger.error(f"Failed to describe job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to describe job")


@router.get("/{job_name}/status", response_model=dict)
async def get_job_status(job_name: str, storage=Depends(get_storage)):
    """Get the status of a specific job"""
    try:
        # Check if job exists
        job_config = storage.get_job_config(job_name)
        if not job_config:
            logger.error(f"Job {job_name} not found")
            raise HTTPException(status_code=404, detail="Not Found")

        # Get the latest job execution
        executions = storage.get_job_executions(job_name)

        if not executions:
            return {"id": None, "status": "not_started", "result": None, "timestamp": None, "job_name": job_name}

        latest_execution = executions[0]  # Assuming sorted by timestamp desc

        return {
            "id": latest_execution.id,
            "status": latest_execution.status,
            "result": latest_execution.result,
            "timestamp": latest_execution.updatedAt,
            "job_name": job_name,
        }

    except Exception as e:
        logger.error(f"Failed to get job status: {e}", exc_info=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Failed to get job status")


@router.post("/{job_name}/trigger", response_model=dict, status_code=201)
async def trigger_job(job_name: str, storage=Depends(get_storage)):
    """Trigger a job execution"""
    try:
        # Check if job exists
        job_config = storage.get_job_config(job_name)
        if not job_config:
            raise HTTPException(status_code=404, detail=f"Job {job_name} not found")

        # Create a new job execution record with timestamp in ID to ensure uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        execution = JobExecutionModel(
            id=f"{job_name}_{timestamp}",  # Add timestamp to make ID unique
            job_name=job_name,
            status="queued",
            result=None,
        )

        # Save the initial execution record
        storage.create_job_execution(execution)

        # Trigger the actual job execution
        from agentic_inventory.backend.jobs.scheduler import scheduler

        scheduler.scheduler.add_job(
            func=scheduler.execute_job_wrapper,
            args=[job_name, job_config.model_dump()],
            trigger="date",
            id=f"job_{execution.id}",  # Use the same unique ID
            replace_existing=True,
        )

        return {"message": f"Job {job_name} triggered", "execution_id": execution.id, "status": "queued"}

    except Exception as e:
        logger.error(f"Failed to trigger job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to trigger job")


@router.post("/{job_name}/cancel", response_model=dict, status_code=202)
async def cancel_job(job_name: str, storage=Depends(get_storage)):
    """Cancel a running job"""
    try:
        # Check if job exists
        job_config = storage.get_job_config(job_name)
        if not job_config:
            raise HTTPException(status_code=404, detail=f"Job {job_name} not found")

        # Get latest execution
        executions = storage.get_job_executions(job_name)
        if not executions:
            raise HTTPException(status_code=400, detail=f"No executions found for job {job_name}")

        latest_execution = executions[0]
        if latest_execution.status not in [JobStatus.QUEUED, JobStatus.EXECUTING]:
            raise HTTPException(
                status_code=400,
                detail=f"Job {job_name} cannot be cancelled (current status: {latest_execution.status})",
            )

        # Update the execution status
        latest_execution.status = JobStatus.CANCELLED
        storage.update_job_execution(latest_execution)

        return {"message": f"Job {job_name} cancelled"}

    except Exception as e:
        logger.error(f"Failed to cancel job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to cancel job")


@router.delete("/{job_name}", status_code=204)
async def delete_job(job_name: str, storage=Depends(get_storage)):
    """Delete a job configuration"""
    try:
        # Check if job exists
        job_config = storage.get_job_config(job_name)
        if not job_config:
            raise HTTPException(status_code=404, detail=f"Job {job_name} not found")

        # Delete the job config
        storage.delete_job_config(job_name)
        return {}
    except Exception as e:
        logger.error(f"Failed to delete job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete job")
