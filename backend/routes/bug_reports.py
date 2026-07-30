"""
Bug Reports API Routes - User and Admin endpoints for bug report management
"""

import logging
from uuid import UUID
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from database.connection import get_db
from models.user import User
from models.bug_report import BugReport
from services.bug_report_service import BugReportService
from routes.auth import get_current_user
from dependencies.admin import get_admin_user, require_manage_level

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bug-reports", tags=["Bug Reports"])


# ──────────────────────────────────────────────────────────────────
# Pydantic Models
# ──────────────────────────────────────────────────────────────────

class BugReportCreate(BaseModel):
    """Schema for creating a bug report"""
    title: str = Field(..., min_length=5, max_length=255, description="Brief title of the bug")
    description: str = Field(..., min_length=10, description="Detailed description of the issue")
    severity: str = Field("medium", pattern="^(low|medium|high|critical)$", description="Severity level")
    category: str = Field("General", max_length=100, description="Category of the bug")
    page_url: Optional[str] = Field(None, max_length=500, description="URL of the page where bug occurred")
    component_name: Optional[str] = Field(None, max_length=200, description="Component where bug occurred")
    user_agent: Optional[str] = Field(None, max_length=500, description="User agent info")
    screenshot_url: Optional[str] = Field(None, max_length=500, description="Screenshot URL")
    attachment_url: Optional[str] = Field(None, max_length=500, description="Attachment URL")
    browser: Optional[str] = Field(None, max_length=100, description="Browser information")
    os_info: Optional[str] = Field(None, max_length=100, description="Operating system info")
    app_version: Optional[str] = Field(None, max_length=50, description="App version")
    error_message: Optional[str] = Field(None, description="Error message if applicable")
    steps_to_reproduce: Optional[str] = Field(None, description="Steps to reproduce the bug")
    expected_behavior: Optional[str] = Field(None, description="Expected behavior")
    actual_behavior: Optional[str] = Field(None, description="Actual behavior")


class BugReportResponse(BaseModel):
    """Schema for bug report response"""
    id: str
    user_id: str
    title: str
    description: str
    severity: str
    category: str
    status: str
    page_url: Optional[str]
    component_name: Optional[str]
    screenshot_url: Optional[str]
    browser: Optional[str]
    os_info: Optional[str]
    error_message: Optional[str]
    steps_to_reproduce: Optional[str]
    expected_behavior: Optional[str]
    actual_behavior: Optional[str]
    admin_notes: Optional[str]
    assigned_to: Optional[str]
    created_at: str
    updated_at: str
    resolved_at: Optional[str]
    user_email: Optional[str] = None

    class Config:
        from_attributes = True


class BugReportUpdateStatus(BaseModel):
    """Schema for updating bug report status"""
    status: str = Field(..., pattern="^(open|in-review|in-progress|resolved|closed|wont-fix)$")
    admin_notes: Optional[str] = Field(None, description="Notes from admin")
    assigned_to: Optional[str] = Field(None, description="Admin user ID to assign to")


class BugReportAdminNote(BaseModel):
    """Schema for adding admin notes"""
    notes: str = Field(..., min_length=1, description="Admin notes")
    assigned_to: Optional[str] = Field(None, description="Admin user ID to assign to")


class BugReportStats(BaseModel):
    """Schema for bug report statistics"""
    total: int
    by_status: dict
    by_severity: dict
    recent_reports: List[dict]


# ──────────────────────────────────────────────────────────────────
# Utility Functions
# ──────────────────────────────────────────────────────────────────

def _format_bug_report(report: BugReport) -> BugReportResponse:
    """Format bug report for response"""
    return BugReportResponse(
        id=str(report.id),
        user_id=str(report.user_id),
        title=report.title,
        description=report.description,
        severity=report.severity,
        category=report.category,
        status=report.status,
        page_url=report.page_url,
        component_name=report.component_name,
        screenshot_url=report.screenshot_url,
        browser=report.browser,
        os_info=report.os_info,
        error_message=report.error_message,
        steps_to_reproduce=report.steps_to_reproduce,
        expected_behavior=report.expected_behavior,
        actual_behavior=report.actual_behavior,
        admin_notes=report.admin_notes,
        assigned_to=str(report.assigned_to) if report.assigned_to else None,
        created_at=report.created_at.isoformat(),
        updated_at=report.updated_at.isoformat(),
        resolved_at=report.resolved_at.isoformat() if report.resolved_at else None,
        user_email=None,
    )


# ──────────────────────────────────────────────────────────────────
# User Endpoints
# ──────────────────────────────────────────────────────────────────

@router.post("/submit", response_model=BugReportResponse, tags=["User"])
async def submit_bug_report(
    report_data: BugReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a new bug report
    
    - **title**: Brief title of the bug (5-255 chars)
    - **description**: Detailed description (minimum 10 chars)
    - **severity**: low, medium, high, or critical
    - **category**: Bug category (e.g., "UI Bug", "Performance", etc.)
    """
    try:
        bug_report = await BugReportService.create_bug_report(
            db=db,
            user_id=current_user.id,
            title=report_data.title,
            description=report_data.description,
            severity=report_data.severity,
            category=report_data.category,
            page_url=report_data.page_url,
            component_name=report_data.component_name,
            user_agent=report_data.user_agent,
            screenshot_url=report_data.screenshot_url,
            attachment_url=report_data.attachment_url,
            browser=report_data.browser,
            os_info=report_data.os_info,
            app_version=report_data.app_version,
            error_message=report_data.error_message,
            steps_to_reproduce=report_data.steps_to_reproduce,
            expected_behavior=report_data.expected_behavior,
            actual_behavior=report_data.actual_behavior,
        )
        
        logger.info(f"Bug report submitted by user {current_user.email}: {bug_report.id}")
        return _format_bug_report(bug_report)
    
    except Exception as e:
        logger.error(f"Error submitting bug report: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit bug report")


@router.get("/my-reports", response_model=dict, tags=["User"])
async def get_my_reports(
    status: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get user's own bug reports
    
    - **status**: Optional filter by status (open, in-review, in-progress, resolved, etc.)
    """
    try:
        reports, total = await BugReportService.get_user_reports(
            db=db,
            user_id=current_user.id,
            status=status,
            skip=skip,
            limit=limit,
        )
        
        return {
            "items": [_format_bug_report(r) for r in reports],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    
    except Exception as e:
        logger.error(f"Error fetching user reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch reports")


@router.get("/{report_id}", response_model=BugReportResponse, tags=["User"])
async def get_bug_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific bug report (user can only see their own)"""
    try:
        report_uuid = UUID(report_id)
        report = await BugReportService.get_bug_report(db, report_uuid)
        
        if not report:
            raise HTTPException(status_code=404, detail="Bug report not found")
        
        # User can only see their own reports unless they're admin
        if report.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized to view this report")
        
        return _format_bug_report(report)
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID")
    except Exception as e:
        logger.error(f"Error fetching bug report: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch report")


@router.delete("/{report_id}", tags=["User"])
async def delete_bug_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user's own bug report."""
    try:
        report_uuid = UUID(report_id)
        report = await BugReportService.get_bug_report(db, report_uuid)

        if not report:
            raise HTTPException(status_code=404, detail="Bug report not found")

        if report.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized to delete this report")

        deleted = await BugReportService.delete_bug_report(db, report_uuid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Bug report not found")

        return {"success": True, "message": "Bug report deleted successfully"}

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting bug report: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete report")


# ──────────────────────────────────────────────────────────────────
# Admin Endpoints
# ──────────────────────────────────────────────────────────────────

@router.get("/admin/all", response_model=dict, tags=["Admin"])
async def get_all_reports(
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    category: Optional[str] = Query(None, description="Filter by category"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all bug reports (Admin only - Manage level or above)
    
    - **status**: Filter by status
    - **severity**: Filter by severity (low, medium, high, critical)
    - **category**: Filter by category
    """
    try:
        reports, total = await BugReportService.get_all_reports(
            db=db,
            status=status,
            severity=severity,
            category=category,
            skip=skip,
            limit=limit,
        )
        
        return {
            "items": [_format_bug_report(r) for r in reports],
            "total": total,
            "skip": skip,
            "limit": limit,
            "filters": {
                "status": status,
                "severity": severity,
                "category": category,
            },
        }
    
    except Exception as e:
        logger.error(f"Error fetching all bug reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch reports")


@router.post("/{report_id}/update-status", response_model=BugReportResponse, tags=["Admin"])
async def update_report_status(
    report_id: str,
    update_data: BugReportUpdateStatus,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update bug report status and add admin notes (Admin only)
    
    - **status**: New status (open, in-review, in-progress, resolved, closed, wont-fix)
    """
    try:
        report_uuid = UUID(report_id)
        
        assigned_to = None
        if update_data.assigned_to:
            try:
                assigned_to = UUID(update_data.assigned_to)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid assigned_to UUID")
        
        report = await BugReportService.update_report_status(
            db=db,
            report_id=report_uuid,
            status=update_data.status,
            admin_notes=update_data.admin_notes,
            assigned_to=assigned_to,
        )
        
        if not report:
            raise HTTPException(status_code=404, detail="Bug report not found")
        
        logger.info(f"Bug report {report_id} status updated to {update_data.status} by admin {current_user.email}")
        return _format_bug_report(report)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid format: {str(e)}")
    except Exception as e:
        logger.error(f"Error updating bug report status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update report")


@router.post("/{report_id}/add-notes", response_model=BugReportResponse, tags=["Admin"])
async def add_admin_notes(
    report_id: str,
    note_data: BugReportAdminNote,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Add admin notes to a bug report (Admin only)
    """
    try:
        report_uuid = UUID(report_id)
        
        assigned_to = None
        if note_data.assigned_to:
            try:
                assigned_to = UUID(note_data.assigned_to)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid assigned_to UUID")
        
        report = await BugReportService.add_admin_notes(
            db=db,
            report_id=report_uuid,
            notes=note_data.notes,
            assigned_to=assigned_to,
        )
        
        if not report:
            raise HTTPException(status_code=404, detail="Bug report not found")
        
        logger.info(f"Admin notes added to bug report {report_id} by {current_user.email}")
        return _format_bug_report(report)
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID")
    except Exception as e:
        logger.error(f"Error adding admin notes: {e}")
        raise HTTPException(status_code=500, detail="Failed to add notes")


@router.get("/admin/dashboard-stats", response_model=BugReportStats, tags=["Admin"])
async def get_dashboard_stats(
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get bug report statistics for admin dashboard (Admin only)
    """
    try:
        stats = await BugReportService.get_dashboard_stats(db)
        return BugReportStats(**stats)
    
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch statistics")


@router.get("/admin/by-user/{user_id}", response_model=dict, tags=["Admin"])
async def get_user_reports_admin(
    user_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all reports from a specific user (Admin only)
    """
    try:
        user_uuid = UUID(user_id)
        reports, total = await BugReportService.get_user_reports(
            db=db,
            user_id=user_uuid,
            skip=skip,
            limit=limit,
        )
        
        return {
            "items": [_format_bug_report(r) for r in reports],
            "total": total,
            "skip": skip,
            "limit": limit,
            "user_id": user_id,
        }
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except Exception as e:
        logger.error(f"Error fetching user reports (admin): {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch reports")
