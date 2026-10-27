import { readFile } from 'node:fs/promises';
import { request } from 'node:http';

async function invoke(options, path, body, signal) {
  const token = await readFile(options.tokenPath, 'utf8');
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = request({socketPath: options.socketPath, path, method: 'POST', headers: {
      authorization: `Bearer ${token.trim()}`, 'content-type': 'application/json',
      'content-length': Buffer.byteLength(data),
    }}, response => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        text += chunk;
        if (text.length > 65536) req.destroy(new Error('Attachment receipt too large'));
      });
      response.on('end', () => { try { resolve(JSON.parse(text)); } catch { reject(new Error('Invalid attachment receipt')); } });
      response.on('error', reject);
    });
    const abort = () => req.destroy(new Error('Attachment submission interrupted'));
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, {once: true});
    req.on('close', () => signal?.removeEventListener('abort', abort));
    req.on('error', reject);
    req.setTimeout(120000, () => req.destroy(new Error('Attachment submission timed out')));
    req.end(data);
  });
}

export default {
  id: 'qq.attachment-delivery',
  async setup(ctx) {
    const options = {
      socketPath: ctx.options.socketPath,
      tokenPath: ctx.options.tokenPath,
    };
    await ctx.tool.transform(editor => {
      editor.namespace({name: 'qq', description: '发送附件到本次真实 QQ 聊天。'});
      editor.add({
        name: 'delivery_context',
        description: '仅在尚不清楚本轮输出目录时查询；已知本轮文件路径可直接调用 qq_send_files，无需先查目录或限制。',
        input: {type: 'object', properties: {}, additionalProperties: false},
        options: {namespace: 'qq', codemode: false},
        async execute(input, context) {
          try {
            const result = await invoke(options, '/context', {session_id: context.sessionID}, context.signal);
            return {content: JSON.stringify(result)};
          } catch {
            return {content: JSON.stringify({available: false})};
          }
        },
      });
      editor.add({
        name: 'send_files',
        description: '直接提交本轮图片、视频、文档或音频路径，无需预先查询目录或限制；自动绑定真实聊天，queued 表示已受理，尚未确认送达。',
        input: {type: 'object', properties: {files: {type: 'array', minItems: 1, maxItems: 50, items: {
          type: 'object', properties: {
            path: {type: 'string', minLength: 1, maxLength: 4096},
            name: {type: 'string', minLength: 1, maxLength: 200},
            kind: {type: 'string', enum: ['auto', 'image', 'video', 'audio', 'file']},
          }, required: ['path'], additionalProperties: false,
        }}}, required: ['files'], additionalProperties: false},
        options: {namespace: 'qq', codemode: false},
        async execute(input, context) {
          try {
            const result = await invoke(options, '/call', {
              session_id: context.sessionID, call_id: context.id, name: 'send_files', arguments: input,
            }, context.signal);
            return {content: JSON.stringify(result)};
          } catch {
            return {content: JSON.stringify({ok: false, status: 'unconfirmed', message: '未取得附件排队确认，不表示已发送；不要换工具调用编号重复提交，也不要输出内部清单。'})};
          }
        },
      });
    });
    await ctx.session.hook('context', async event => {
      let available = false;
      try { available = (await invoke(options, '/context', {session_id: event.sessionID})).available === true; } catch {}
      if (!available) {
        delete event.tools.qq_send_files;
        delete event.tools.qq_delivery_context;
      }
    });
  },
};
