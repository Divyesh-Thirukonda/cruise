"use strict";

document.getElementById("verify").addEventListener("click", () => {
  document.getElementById("result").textContent = "Verified: " + document.getElementById("answer").value;
});
