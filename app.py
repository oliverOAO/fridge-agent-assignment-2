import json
import sqlite3

import streamlit as st

from fridge.agent import FridgeAgent
from fridge.catalog import UserError
from fridge.ollama import Ollama


def show_amounts(items):
    st.table([{'食材': item['name'], '數量': item['quantity'], '單位': item['unit']} for item in items])


def edit_inventory(agent):
    st.subheader('更新庫存')
    name = st.selectbox('食材', sorted(agent.catalog.units))
    with st.form('inventory_editor'):
        qty = st.number_input(f'現有總量（{agent.catalog.units[name]}，0 表示移除）', min_value=0,
                              max_value=10_000_000, step=1)
        if st.form_submit_button('儲存庫存'):
            agent.set_item(name, qty)
            st.success(f'已更新{name}。')
    items = agent.inventory()['items']
    if items:
        show_amounts(items)
    else:
        st.info('目前沒有登錄食材。')


def plan_meal(agent):
    st.subheader('規劃一餐')
    model_mode = st.radio('規劃模式', ['離線規則', 'Ollama'], horizontal=True)
    with st.form('meal_planner'):
        a, b, c = st.columns(3)
        servings = a.selectbox('人數', [1, 2])
        dishes = b.selectbox('道數', [1, 2])
        minutes = c.number_input('時間上限（分鐘）', min_value=1, max_value=120, value=30, step=1)
        names = sorted(agent.catalog.units)
        excluded = st.multiselect('排除食材', names)
        priority = st.multiselect('優先使用', names)
        shopping = st.checkbox('允許採買缺少的食材')
        preference = st.text_input('補充料理偏好', max_chars=300) if model_mode == 'Ollama' else ''
        if st.form_submit_button('規劃菜單', type='primary'):
            with st.spinner('正在查詢庫存及食譜…'):
                st.session_state['result'] = agent.plan(servings, minutes, dishes, excluded, priority, shopping,
                                                       preference, Ollama() if model_mode == 'Ollama' else None)

    result = st.session_state.get('result')
    if result is None:
        return
    st.caption(f'本次規劃使用 {result["mode"]}')
    if result['status'] == 'ready':
        st.success(result['message'])
    elif result['status'] == 'error':
        st.error(result['message'])
    else:
        st.warning(result['message'])
    if result.get('recipes'):
        st.write(f'{result["servings"]} 人份，預估共 {result["minutes"]} 分鐘。')
        for recipe in result['recipes']:
            with st.expander(recipe['name'], expanded=True):
                for index, step in enumerate(recipe['steps'], 1):
                    st.write(f'{index}. {step}')
        st.write('食材用量')
        show_amounts(result['required'])
    if result.get('missing'):
        st.write('缺少的食材')
        show_amounts(result['missing'])
    if result['status'] == 'ready':
        if st.button('確認已完成料理並扣除上述用量', key=result['meal_id']):
            try:
                confirmation = agent.confirm(result['meal_id'])
                if confirmation['status'] == 'already_confirmed':
                    st.info('這份菜單已扣除庫存。')
                else:
                    st.success('庫存已更新。')
            except UserError as error:
                st.warning(str(error))
    with st.expander('Agent 執行紀錄'):
        st.json(result['trace'], expanded=False)
        st.download_button('下載執行紀錄', json.dumps(result['trace'], ensure_ascii=False, indent=2),
                           file_name='agent-trace.json', mime='application/json')


st.set_page_config(page_title='冰箱食材與餐食規劃助手', layout='centered')
st.title('冰箱食材與餐食規劃助手')
st.caption('登錄手邊食材，規劃 1～2 人份的餐點。')
try:
    agent = FridgeAgent()
    if st.radio('功能', ['冰箱庫存', '餐食規劃'], horizontal=True, label_visibility='collapsed') == '冰箱庫存':
        edit_inventory(agent)
    else:
        plan_meal(agent)
except (UserError, OSError, sqlite3.Error) as error:
    st.error(f'操作無法完成：{error}')
