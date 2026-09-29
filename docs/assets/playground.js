'use strict';
(() => {
  const API = 'https://api.tokenlabs.run';
  const $ = id => document.getElementById(id);
  let history = [];
  let controller = null;
  let loadingModels = false;

  function status(text, error = false) {
    $('status').textContent = text;
    $('status').classList.toggle('error', error);
  }
  function controls() {
    const busy = Boolean(controller);
    $('send').disabled = busy || loadingModels || !$('model').value;
    $('stop').hidden = !busy;
    for (const id of ['model', 'refresh', 'clear', 'api-key', 'system', 'temperature', 'max-tokens']) {
      $(id).disabled = busy || (loadingModels && ['model', 'refresh'].includes(id));
    }
    $('prompt').readOnly = busy;
  }
  function clear() {
    history = [];
    $('messages').replaceChildren();
    $('empty').hidden = false;
    status($('model').value ? 'Ready when you are.' : 'Choose an available model to start.');
  }
  async function loadModels() {
    const previous = $('model').value;
    loadingModels = true;
    controls();
    status('Checking available models…');
    try {
      const response = await fetch(`${API}/v1/models`, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Model discovery is unavailable. Try refreshing in a moment.');
      const body = await response.json();
      if (!Array.isArray(body.data)) throw new Error('The model list could not be read. Try refreshing.');
      const ids = [...new Set(body.data.filter(model => typeof model?.id === 'string' && model.id.trim()).map(model => model.id))];
      $('model').replaceChildren(...ids.map(id => new Option(id, id)));
      if (!ids.length) $('model').add(new Option('No models available', ''));
      if (ids.includes(previous)) $('model').value = previous;
      if (previous && previous !== $('model').value) clear();
      status(ids.length ? 'Ready when you are.' : 'No models are available right now. Try refreshing later.');
    } catch (error) {
      $('model').replaceChildren(new Option('Models unavailable', ''));
      status(error.name === 'TimeoutError' ? 'Model discovery timed out. Try refreshing.' : error.message, true);
    } finally {
      loadingModels = false;
      controls();
    }
  }
  function message(role, text) {
    $('empty').hidden = true;
    const article = document.createElement('article');
    article.className = `message ${role}`;
    const label = document.createElement('h3');
    label.textContent = role === 'user' ? 'You' : $('model').value;
    const content = document.createElement('p');
    content.textContent = text;
    article.append(label, content);
    $('messages').append(article);
    return {article, content};
  }
  $('refresh').addEventListener('click', loadModels);
  $('clear').addEventListener('click', () => {clear(); $('prompt').focus();});
  $('model').addEventListener('change', () => {clear(); controls();});
  $('stop').addEventListener('click', () => controller?.abort());
  for (const button of document.querySelectorAll('[data-prompt]')) {
    button.addEventListener('click', () => {$('prompt').value = button.dataset.prompt; $('prompt').focus();});
  }
  $('prompt').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!$('send').disabled) $('chat-form').requestSubmit();
    }
  });
  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (controller || loadingModels || !$('model').value) return;
    const prompt = $('prompt').value.trim();
    const key = $('api-key').value.trim();
    if (!prompt || !key) {status('Enter a message and your provider API key.', true); return;}
    controller = new AbortController();
    controls();
    const user = message('user', prompt);
    const reply = message('assistant', '');
    status('Waiting for a response…');
    let text = '', reasoning = '', thinking, finishReason;
    const messages = [...history, {role: 'user', content: prompt}];
    if ($('system').value.trim()) messages.unshift({role: 'system', content: $('system').value.trim()});
    try {
      const response = await fetch(`${API}/openrouter/v1/chat/completions`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', Authorization: `Bearer ${key}`},
        body: JSON.stringify({model: $('model').value, messages, stream: true,
          chat_template_kwargs: {enable_thinking: false},
          temperature: Number($('temperature').value), max_tokens: Number($('max-tokens').value)}),
        signal: controller.signal
      });
      if (!response.ok) {
        const errors = {401: 'That provider API key was not accepted.', 403: 'This key does not have access.',
          429: 'The service is busy. Please try again shortly.', 503: 'The model is temporarily unavailable.'};
        throw new Error(errors[response.status] || `The request failed (HTTP ${response.status}). Try a shorter conversation or start a new chat.`);
      }
      if (!response.body) throw new Error('Streaming is unavailable in this browser.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '', done = false;
      function consume(frame) {
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!data) return;
        if (data.trim() === '[DONE]') {done = true; return;}
        const chunk = JSON.parse(data);
        if (chunk.error) throw new Error('The model could not complete this response. Please try again.');
        const choice = chunk.choices?.[0];
        if (choice?.finish_reason) finishReason = choice.finish_reason;
        const delta = choice?.delta;
        if (!delta) return;
        const chat = document.querySelector('.chat');
        const follow = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 100;
        if (typeof delta.reasoning_content === 'string' || typeof delta.reasoning === 'string') {
          reasoning += delta.reasoning_content || delta.reasoning;
          if (!thinking) {
            thinking = document.createElement('details');
            const summary = document.createElement('summary'); summary.textContent = 'Reasoning';
            thinking.append(summary, document.createElement('pre'));
            reply.article.insertBefore(thinking, reply.content);
          }
          thinking.lastChild.textContent = reasoning;
          status('Thinking…');
        }
        if (typeof delta.content === 'string') {text += delta.content; reply.content.textContent = text; status('Receiving response…');}
        if (follow) chat.scrollTop = chat.scrollHeight;
      }
      try {
        while (!done) {
          const next = await reader.read();
          buffer += decoder.decode(next.value, {stream: !next.done});
          let match;
          while ((match = /\r?\n\r?\n/.exec(buffer))) {
            const frame = buffer.slice(0, match.index);
            buffer = buffer.slice(match.index + match[0].length);
            consume(frame);
            if (done) break;
          }
          if (next.done) {if (buffer.trim()) consume(buffer); break;}
        }
      } finally {await reader.cancel().catch(() => {});}
      if (!done) throw new Error('The connection ended before the response finished. Please try again.');
      if (text) {
        history.push({role: 'user', content: prompt}, {role: 'assistant', content: text});
        $('prompt').value = '';
        status(finishReason === 'length'
          ? 'Output limit reached. Increase max output tokens in Settings for a longer answer.'
          : 'Response complete.');
      } else {
        status('No answer was returned. Try increasing max output tokens in Settings.', true);
      }
    } catch (error) {
      status(error.name === 'AbortError' ? 'Stopped. You can edit your message and try again.' : error.message, error.name !== 'AbortError');
      if (!text && !reasoning) {user.article.remove(); reply.article.remove(); $('empty').hidden = history.length > 0;}
    } finally {
      controller = null;
      controls();
      $('prompt').focus();
    }
  });
  loadModels();
})();
