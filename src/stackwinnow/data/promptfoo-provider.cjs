// StackWinnow's deterministic fixture provider. It makes no network/model calls.
module.exports = class StackWinnowFixtureProvider {
  id() {
    return 'stackwinnow-deterministic-uppercase';
  }

  async callApi(prompt, context) {
    const deliberateFailure = String(context?.vars?.stackwinnowFail) === 'true';
    return {
      output: deliberateFailure ? 'INTENTIONAL MISMATCH' : String(prompt).toUpperCase(),
      tokenUsage: { total: 0, prompt: 0, completion: 0 },
      cost: 0,
    };
  }
};
