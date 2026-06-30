"""
Bug Report Service - Handles creation and management of user bug reports
"""

import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select, desc, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models.bug_report import BugReport
from models.user import User

logger = logging.getLogger(__name__)


class BugReportService:
    """Service for managing bug reports"""

    @staticmethod
    async def create_bug_report(
        db: AsyncSession,
        user_id: UUID,
        title: str,
        description: str,
        severity: str = "medium",
        category: str = "General",
        page_url: Optional[str] = None,
        component_name: Optional[str] = None,
        user_agent: Optional[str] = None,
        screenshot_url: Optional[str] = None,
        attachment_url: Optional[str] = None,
        browser: Optional[str] = None,
        os_info: Optional[str] = None,
        app_version: Optional[str] = None,
        error_message: Optional[str] = None,
        steps_to_reproduce: Optional[str] = None,
        expected_behavior: Optional[str] = None,
        actual_behavior: Optional[str] = None,
    ) -> BugReport:
        """Create a new bug report"""
        
        bug_report = BugReport(
            user_id=user_id,
            title=title,
            description=description,
            severity=severity.lower(),
            category=category,
            page_url=page_url,
            component_name=component_name,
            user_agent=user_agent,
            screenshot_url=screenshot_url,
            attachment_url=attachment_url,
            browser=browser,
            os_info=os_info,
            app_version=app_version,
            error_message=error_message,
            steps_to_reproduce=steps_to_reproduce,
            expected_behavior=expected_behavior,
            actual_behavior=actual_behavior,
        )
        
        db.add(bug_report)
        await db.commit()
        await db.refresh(bug_report)
        
        logger.info(f"Bug report created: {bug_report.id} by user {user_id}")
        return bug_report

    @staticmethod
    async def get_bug_report(db: AsyncSession, report_id: UUID) -> Optional[BugReport]:
        """Get a single bug report"""
        stmt = select(BugReport).where(BugReport.id == report_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_user_reports(
        db: AsyncSession,
        user_id: UUID,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[BugReport], int]:
        """Get bug reports for a specific user"""
        
        query = select(BugReport).where(BugReport.user_id == user_id)
        
        if status:
            query = query.where(BugReport.status == status)
        
        # Get total count
        count_stmt = select(BugReport).where(BugReport.user_id == user_id)
        if status:
            count_stmt = count_stmt.where(BugReport.status == status)
        count_result = await db.execute(count_stmt)
        total = len(count_result.scalars().all())
        
        query = query.order_by(desc(BugReport.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        reports = result.scalars().all()
        
        return reports, total

    @staticmethod
    async def get_all_reports(
        db: AsyncSession,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[List[BugReport], int]:
        """Get all bug reports (admin view)"""
        
        conditions = []
        
        if status:
            conditions.append(BugReport.status == status)
        if severity:
            conditions.append(BugReport.severity == severity)
        if category:
            conditions.append(BugReport.category == category)
        
        where_clause = and_(*conditions) if conditions else None
        
        if where_clause is not None:
            query = select(BugReport).where(where_clause)
            count_stmt = select(BugReport).where(where_clause)
        else:
            query = select(BugReport)
            count_stmt = select(BugReport)
        
        # Count total
        count_result = await db.execute(count_stmt)
        total = len(count_result.scalars().all())
        
        query = query.order_by(desc(BugReport.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        reports = result.scalars().all()
        
        return reports, total

    @staticmethod
    async def get_reports_by_filters(
        db: AsyncSession,
        status: Optional[List[str]] = None,
        severity: Optional[List[str]] = None,
        category: Optional[List[str]] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[List[BugReport], int]:
        """Get bug reports with multiple filter options"""
        
        conditions = []
        
        if status:
            conditions.append(BugReport.status.in_(status))
        if severity:
            conditions.append(BugReport.severity.in_(severity))
        if category:
            conditions.append(BugReport.category.in_(category))
        
        where_clause = and_(*conditions) if conditions else None
        
        if where_clause is not None:
            query = select(BugReport).where(where_clause)
            count_stmt = select(BugReport).where(where_clause)
        else:
            query = select(BugReport)
            count_stmt = select(BugReport)
        
        # Count total
        count_result = await db.execute(count_stmt)
        total = len(count_result.scalars().all())
        
        query = query.order_by(desc(BugReport.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        reports = result.scalars().all()
        
        return reports, total

    @staticmethod
    async def update_report_status(
        db: AsyncSession,
        report_id: UUID,
        status: str,
        admin_notes: Optional[str] = None,
        assigned_to: Optional[UUID] = None,
    ) -> Optional[BugReport]:
        """Update bug report status"""
        
        report = await BugReportService.get_bug_report(db, report_id)
        if not report:
            return None
        
        report.status = status
        if admin_notes:
            report.admin_notes = admin_notes
        if assigned_to:
            report.assigned_to = assigned_to
        
        if status == "resolved":
            report.resolved_at = datetime.now(timezone.utc)
        
        report.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(report)
        
        logger.info(f"Bug report {report_id} status updated to {status}")
        return report

    @staticmethod
    async def add_admin_notes(
        db: AsyncSession,
        report_id: UUID,
        notes: str,
        assigned_to: Optional[UUID] = None,
    ) -> Optional[BugReport]:
        """Add or update admin notes on a bug report"""
        
        report = await BugReportService.get_bug_report(db, report_id)
        if not report:
            return None
        
        existing_notes = report.admin_notes or ""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        report.admin_notes = f"{existing_notes}\n[{timestamp}]: {notes}".strip()
        
        if assigned_to:
            report.assigned_to = assigned_to
        
        report.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(report)
        
        logger.info(f"Admin notes added to bug report {report_id}")
        return report

    @staticmethod
    async def delete_bug_report(
        db: AsyncSession,
        report_id: UUID,
    ) -> bool:
        """Delete a bug report."""

        report = await BugReportService.get_bug_report(db, report_id)
        if not report:
            return False

        await db.delete(report)
        await db.commit()

        logger.info(f"Bug report deleted: {report_id}")
        return True

    @staticmethod
    async def get_dashboard_stats(db: AsyncSession) -> dict:
        """Get bug report statistics for admin dashboard"""
        
        # Total reports
        total_result = await db.execute(select(BugReport))
        total = len(total_result.scalars().all())
        
        # By status
        statuses = ["open", "in-review", "in-progress", "resolved", "closed", "wont-fix"]
        status_counts = {}
        for status in statuses:
            result = await db.execute(
                select(BugReport).where(BugReport.status == status)
            )
            status_counts[status] = len(result.scalars().all())
        
        # By severity
        severities = ["low", "medium", "high", "critical"]
        severity_counts = {}
        for severity in severities:
            result = await db.execute(
                select(BugReport).where(BugReport.severity == severity)
            )
            severity_counts[severity] = len(result.scalars().all())
        
        # Recent reports
        recent_result = await db.execute(
            select(BugReport).order_by(desc(BugReport.created_at)).limit(10)
        )
        recent_reports = recent_result.scalars().all()
        
        return {
            "total": total,
            "by_status": status_counts,
            "by_severity": severity_counts,
            "recent_reports": [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "severity": r.severity,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                    "user_email": None,
                }
                for r in recent_reports
            ],
        }
