'use strict';
const { noStore, objectBody, HttpError, fail } = require('../server/modulate-http.cjs');
const { register } = require('../server/device-registry.cjs');
module.exports = async function handler(req, res) {
  noStore(res);
  try {
    if (req.method !== 'POST') throw new HttpError(405, 'Method not allowed.');
    const secret = process.env.MODULATE_REMOTE_SECRET;
    if (!secret || secret.length < 32) throw new HttpError(503, 'Device discovery is not configured.');
    return res.status(200).json(await register(objectBody(req, 1024), req.headers['x-modulate-signature'], secret));
  } catch (error) { return fail(res, error); }
};
