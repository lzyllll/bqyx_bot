const fs = require('fs');
const path = require('path');

// 从当前目录下的 config.json 读取凭据
function getCredentials() {
    const configPath = path.resolve(__dirname, 'config.json');
    if (!fs.existsSync(configPath)) {
        console.error(`❌ 未找到配置文件: ${configPath}`);
        console.error('请在 scripts/ 目录下创建 config.json，格式如下:');
        console.error(JSON.stringify({ appid: 'xxx', secret: 'xxx' }, null, 2));
        process.exit(1);
    }
    try {
        const raw = fs.readFileSync(configPath, 'utf-8').replace(/^\uFEFF/, '');
        const cfg = JSON.parse(raw);
        if (!cfg.appid || !cfg.secret) {
            throw new Error('config.json 中缺少 appid 或 secret');
        }
        return { appid: cfg.appid, secret: cfg.secret };
    } catch (e) {
        console.error(`❌ 读取 ${configPath} 失败:`, e.message);
        process.exit(1);
    }
}

const { appid: APPID, secret: SECRET } = getCredentials();

async function requestJson(url, options = {}) {
    const res = await fetch(url, options);
    let data = null;
    const text = await res.text();
    try {
        data = JSON.parse(text);
    } catch {
        data = text;
    }
    if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${typeof data === 'object' ? JSON.stringify(data) : data}`);
    }
    return data;
}

async function getAccessToken() {
    const data = await requestJson('https://bots.qq.com/app/getAppAccessToken', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            appId: APPID,
            clientSecret: SECRET,
        }),
    });
    return data.access_token;
}

// 严格按照 help.py / reply.py 中注册的指令名称设置（单面板上限 20 个）
const PANEL_ITEMS = [
    // 基础帮助
    { type: 'command', name: '帮助', desc: '查看完整指令菜单与使用说明' },

    // 个人查询 (HELP_MODULE_PERSONAL)
    { type: 'command', name: '我的信息', desc: '查看个人贡献与日常任务进度' },
    { type: 'command', name: '我的战力', desc: '查看角色战力面板与加成汇总' },
    { type: 'command', name: '我的贡献', desc: '查看每日贡献日历墙' },
    { type: 'command', name: '查物品', desc: '查看背包物品及变动对比' },
    { type: 'command', name: '查修罗', desc: '查看修罗塔挑战进度' },

    // 账号绑定 (HELP_MODULE_BIND)
    { type: 'command', name: '我的绑定', desc: '查看当前绑定的账号与存档' },
    { type: 'command', name: '绑定游戏名', desc: '按角色名绑定角色' },
    { type: 'command', name: '绑定uid', desc: '按游戏UID绑定角色' },
    { type: 'command', name: '绑定军队', desc: '为本群绑定指定军队ID' },

    // 军队与本群 (HELP_MODULE_UNION)
    { type: 'command', name: '军队信息', desc: '查看绑定的军队基本信息' },
    { type: 'command', name: '查成员', desc: '查看军团成员列表' },
    { type: 'command', name: '查日贡', desc: '今日达标未达标成员图' },
    { type: 'command', name: '查周贡', desc: '本周达标未达标成员图' },
    { type: 'command', name: '昨日贡献', desc: '昨日日贡排行图' },
    { type: 'command', name: '查争霸', desc: '查看争霸状态与据点分配' },
    { type: 'command', name: '查PK', desc: '查看全军团 PK 积分榜' },

    // 排行模块 (HELP_MODULE_RANK)
    { type: 'command', name: '今日日贡排行', desc: '实时今日日贡排行' },
    { type: 'command', name: '昨日日贡排行', desc: '昨日日贡归档排行' },
    { type: 'command', name: '军队排行', desc: '全服军队战力总排行' },
];

// 单聊底部自定义菜单（严格对应 help 四大模块：账号绑定、个人查询、军队本群、排行PK）
const CUSTOM_MENU = {
    items: [
        {
            type: 'menu',
            name: '账号绑定',
            sub_menu_items: [
                { type: 'send_message', name: '我的绑定', send_message: '我的绑定' },
                { type: 'send_message', name: '绑定游戏名', send_message: '绑定游戏名 ' },
                { type: 'send_message', name: '绑定uid', send_message: '绑定uid ' },
                { type: 'send_message', name: '绑定账号', send_message: '绑定账号 ' },
                { type: 'send_message', name: '绑定军队', send_message: '绑定军队 ' },
            ],
        },
        {
            type: 'menu',
            name: '个人查询',
            sub_menu_items: [
                { type: 'send_message', name: '我的信息', send_message: '我的信息' },
                { type: 'send_message', name: '我的战力', send_message: '我的战力' },
                { type: 'send_message', name: '我的贡献', send_message: '我的贡献' },
                { type: 'send_message', name: '查物品', send_message: '查物品' },
                { type: 'send_message', name: '查修罗', send_message: '查修罗' },
            ],
        },
        {
            type: 'menu',
            name: '军队本群',
            sub_menu_items: [
                { type: 'send_message', name: '军队信息', send_message: '军队信息' },
                { type: 'send_message', name: '查成员', send_message: '查成员' },
                { type: 'send_message', name: '查日贡', send_message: '查日贡' },
                { type: 'send_message', name: '查周贡', send_message: '查周贡' },
                { type: 'send_message', name: '昨日贡献', send_message: '昨日贡献' },
            ],
        },
        {
            type: 'menu',
            name: '排行PK',
            sub_menu_items: [
                { type: 'send_message', name: '今日日贡排行', send_message: '今日日贡排行' },
                { type: 'send_message', name: '昨日日贡排行', send_message: '昨日日贡排行' },
                { type: 'send_message', name: '军队排行', send_message: '军队排行' },
                { type: 'send_message', name: '查PK', send_message: '查PK' },
                { type: 'send_message', name: '帮助', send_message: '帮助' },
            ],
        },
    ],
};

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function syncMenuAndPanel() {
    const token = await getAccessToken();
    const headers = {
        Authorization: `QQBot ${token}`,
        'X-Union-Appid': APPID,
        'Content-Type': 'application/json',
    };

    console.log('=== 1. 设置单聊自定义菜单 (Custom Menu) ===');
    try {
        const menuRes = await requestJson('https://api.sgroup.qq.com/v2/menu', {
            method: 'PUT',
            headers,
            body: JSON.stringify({ menu: CUSTOM_MENU }),
        });
        console.log('✅ 自定义菜单更新成功:', menuRes);
    } catch (e) {
        console.error('❌ 自定义菜单更新失败:', e.message);
    }

    await sleep(2000);

    console.log('\n=== 2. 设置群聊指令面板 (Group Command Panel) ===');
    await setupScopePanel('group', headers);

    await sleep(2000);

    console.log('\n=== 3. 设置单聊指令面板 (C2C Command Panel) ===');
    await setupScopePanel('c2c', headers);
}

async function setupScopePanel(scope, headers) {
    try {
        const listRes = await requestJson(`https://api.sgroup.qq.com/v2/panels?scope=${scope}`, {
            method: 'GET',
            headers,
        });
        const records = listRes?.records || [];
        console.log(`现有 [${scope}] 面板数量: ${records.length}`);

        if (records.length > 0) {
            const existingId = records[0].panel_id;
            console.log(`更新现有面板 [${existingId}] ...`);
            const updateRes = await requestJson(`https://api.sgroup.qq.com/v2/panels/${existingId}`, {
                method: 'PUT',
                headers,
                body: JSON.stringify({
                    panel: {
                        items: PANEL_ITEMS,
                        remark: `冰枪英雄${scope === 'group' ? '群聊' : '单聊'}指令面板`,
                    },
                }),
            });
            console.log(`✅ [${scope}] 面板更新成功:`, updateRes);
        } else {
            console.log(`创建新 [${scope}] 面板 ...`);
            const createRes = await requestJson('https://api.sgroup.qq.com/v2/panels', {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    scope,
                    target_type: 'all',
                    panel: {
                        items: PANEL_ITEMS,
                        remark: `冰枪英雄${scope === 'group' ? '群聊' : '单聊'}指令面板`,
                    },
                }),
            });
            console.log(`✅ [${scope}] 面板创建成功:`, createRes);
        }
    } catch (e) {
        console.error(`❌ [${scope}] 面板设置失败:`, e.message);
    }
}

syncMenuAndPanel().catch(console.error);
