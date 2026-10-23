'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let model = '';
  let revision = 0;
  function example() {
    revision++;
    $('copy-status').textContent = 'Your provider key is never included in the example.';
    $('copy-code').disabled = !model;
    if (!model) {
      $('api-example').textContent = 'Refresh model availability above to prepare an example, or use the full API guide below.';
      return;
    }
    const payload = JSON.stringify({model, messages: [{role: 'user', content: 'Hello!'}], max_tokens: 1024, chat_template_kwargs: {enable_thinking: false}}, null, 2);
    $('api-example').textContent = $('language').value === 'python'
      ? `import os
from openai import OpenAI

client = OpenAI(
    base_url="https://api.tokenlabs.run/openrouter/v1",
    api_key=os.environ["TOKENLABS_API_KEY"],
)
response = client.chat.completions.create(
    model=${JSON.stringify(model)},
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=1024,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
print(response.choices[0].message.content)`
      : `# Set TOKENLABS_API_KEY to your provider key in your environment.
curl https://api.tokenlabs.run/openrouter/v1/chat/completions \\
  -H "Authorization: Bearer $TOKENLABS_API_KEY" \\
  -H 'Content-Type: application/json' \\
  -d '${payload.replaceAll("'", "'\\''")}'`;
  }
  document.addEventListener('model-availability', ({detail}) => {
    model = detail.loading ? '' : detail.model;
    $('availability').dataset.ready = String(Boolean(model));
    $('availability').textContent = detail.loading ? 'Checking model availability…' : model ? 'Available through the Token Labs API' : 'Model availability could not be confirmed';
    $('model-name').textContent = model || (detail.loading ? 'Checking the hosted model…' : 'Model currently unavailable.');
    $('serving-model').textContent = model ? `Model / ${model}` : detail.loading ? 'Checking model…' : detail.message;
    example();
  });
  $('language').addEventListener('change', example);
  $('copy-code').addEventListener('click', async () => {
    const current = revision;
    $('copy-code').disabled = true;
    $('copy-status').textContent = 'Copying…';
    try {
      await navigator.clipboard.writeText($('api-example').textContent);
      if (current === revision) $('copy-status').textContent = 'Copied. Set TOKENLABS_API_KEY in your environment before running.';
    } catch {
      if (current === revision) $('copy-status').textContent = 'Clipboard unavailable. Select the example and copy it manually.';
    } finally {
      if (current === revision) $('copy-code').disabled = !model;
    }
  });
})();
