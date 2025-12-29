# routes/admin.py
from quart import Blueprint, render_template, request, flash, redirect, url_for
from modules.database import db
from utils import get_t, get_current_user, admin_required

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
@admin_required
async def dashboard(): # 函数名可以是 dashboard，但在 url_for 中通过 admin.dashboard 区分
    search_query = request.args.get('q', '').strip()
    all_users = await db.get_all_users_with_stats(search_query)
    current_user = await get_current_user()
    return await render_template('admin_dashboard.html', 
                               users=all_users, 
                               current_user=current_user, 
                               search_query=search_query)

@admin_bp.route('/user/<int:user_id>')
@admin_required
async def view_user_bots(user_id):
    t = get_t()
    target_user = await db.get_user_by_id(user_id)
    if not target_user:
        await flash(t("user_not_found"), 'danger')
        return redirect(url_for('admin.dashboard'))
        
    bots = await db.get_all_bots(user_id)
    current_user = await get_current_user()
    # 复用 dashboard.html 模板
    return await render_template('dashboard.html', 
                               bots=bots, 
                               user=target_user,      
                               current_user=current_user,
                               is_admin_view=True)