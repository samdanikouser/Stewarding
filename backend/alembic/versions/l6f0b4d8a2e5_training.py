"""training: courses, lessons, quizzes, assignments and progress

Revision ID: l6f0b4d8a2e5
Revises: k5e9a3c7f1d4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l6f0b4d8a2e5"
down_revision: Union[str, Sequence[str], None] = "k5e9a3c7f1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "training_course",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(60)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("pass_mark", sa.Integer(), nullable=False),
        sa.Column("certificate", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "training_lesson",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("training_course.id"), nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("external_url", sa.String(500)),
        sa.Column("media_name", sa.String(60)),
        sa.Column("media_original", sa.String(255)),
        sa.Column("media_type", sa.String(100)),
        sa.Column("media_size", sa.Integer()),
    )
    op.create_table(
        "training_question",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("training_lesson.id"), nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
    )
    op.create_table(
        "training_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("training_course.id"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employee.id"), nullable=False, index=True),
        sa.Column("assigned_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("due_on", sa.Date()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("certificate_no", sa.String(30), unique=True),
        sa.Column("score", sa.Integer()),
        sa.UniqueConstraint("course_id", "employee_id"),
    )
    op.create_table(
        "training_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("training_assignment.id"), nullable=False, index=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("training_lesson.id"), nullable=False, index=True),
        sa.Column("position_seconds", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("assignment_id", "lesson_id"),
    )
    op.create_table(
        "training_attempt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("training_assignment.id"), nullable=False, index=True),
        sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("training_lesson.id"), nullable=False, index=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    # everyone may take the training assigned to them; a manager can take the permission from a role under Roles
    op.get_bind().execute(sa.text(
        "INSERT INTO role_permission (role_id, permission) SELECT id, 'training.view' FROM role "
        "WHERE id NOT IN (SELECT role_id FROM role_permission WHERE permission = 'training.view')"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM role_permission WHERE permission = 'training.view'"))
    for table in ("training_attempt", "training_progress", "training_assignment", "training_question", "training_lesson", "training_course"):
        op.drop_table(table)
