// 一次性 node 调用 sign.js 的 get_sign。
// 关键：sign.js 会检测 require/module 来判断是否 CommonJS 环境；MiniRacer 是纯 V8、无 require，
// 走浏览器分支。这里用 vm 沙箱（不暴露 require/module/process）复刻同样的环境。
// 用法: node sign_cli.cjs <md5_param>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const code = fs.readFileSync(path.join(__dirname, 'sign.js'), 'utf8');

const sandbox = {
  window: {},
  document: {},
  navigator: {
    userAgent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
  },
  console: console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: 'sign.js' });

const md5 = process.argv[2] || '';
const out = vm.runInContext('get_sign(' + JSON.stringify(md5) + ')', sandbox);
process.stdout.write(String(out));
