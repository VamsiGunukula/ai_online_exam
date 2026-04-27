(function () {
  const root = document.getElementById("exam-root");
  if (!root) return;

  const video = document.getElementById("exam-video");
  const faceStatusEl = document.getElementById("face-status");
  const warningBar = document.getElementById("warning-bar");
  const warningCountEl = document.getElementById("warning-count");
  const alertRoot = document.getElementById("live-alert-root");
  const warningSoundEl = document.getElementById("warningSound");
  
  const stateUrl = root.dataset.stateUrl;
  const answerUrl = root.dataset.answerUrl;
  const navUrl = root.dataset.navUrl;
  const flagUrl = root.dataset.flagUrl;
  const submitUrl = root.dataset.submitUrl;
  const profileUrl = root.dataset.profileUrl;
  const telemetryUrl = root.dataset.telemetryUrl;

  const timerEl = document.getElementById("timer-display");
  const progressText = document.getElementById("progress-text");
  const progressFill = document.getElementById("progress-fill");
  const questionText = document.getElementById("question-text");
  const questionTopic = document.getElementById("question-topic");
  const optionsEl = document.getElementById("options");
  const navGrid = document.getElementById("nav-grid");
  const btnPrev = document.getElementById("btn-prev");
  const btnNext = document.getElementById("btn-next");
  const btnSubmit = document.getElementById("btn-submit");
  const btnFlag = document.getElementById("btn-flag");
  const flagHint = document.getElementById("flag-hint");
  const examActive = document.getElementById("exam-active");
  const examFinished = document.getElementById("exam-finished");
  const autosaveHint = document.getElementById("autosave-hint");

  let examState = {
    student: {
      name: root.dataset.studentName || "",
      email: root.dataset.studentEmail || "",
      examId: Date.now(),
      date: new Date().toLocaleString(),
    },
    answers: {},
    warnings: [],
    timeline: [],
    lockedQuestions: {},
    warningCount: 0,
    maxWarnings: 5,
    examEnded: false,
    faceDetected: true,
    voiceCooldown: false,
    lastWarningTime: 0,
    totalQuestions: 10,
    currentQuestion: 0,
  };

  let serverState = null;
  let saveTimer = null;
  let pollTimer = null;
  let lastRemaining = null;
  let activeRecognition = null;
  let hasVoiceListener = false;
  let faceMissingStart = null;
  let isLockedNavigating = false;
  let initialized = false;
  let lastSoundTime = 0;

  window.faceInterval = null;
  window.__examMonitorStop = stopMonitors;

  function formatTime(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function addTimeline(eventName) {
    const eventObj = {
      event: eventName,
      question: examState.currentQuestion + 1,
      time: new Date().toLocaleTimeString(),
    };
    examState.timeline.push(eventObj);
    if (telemetryUrl) {
      postTelemetry({
        timeline_event: eventName,
        question_number: examState.currentQuestion + 1,
      });
    }
  }

  function showLiveAlert(message) {
    if (!alertRoot) return;
    alertRoot.textContent = message;
    alertRoot.classList.add("live-alert-visible");
    setTimeout(function () {
      alertRoot.classList.remove("live-alert-visible");
      alertRoot.textContent = "";
    }, 1700);
  }

  function playWarningSound() {
    const now = Date.now();
    if (now - lastSoundTime < 1500) return;
    lastSoundTime = now;

    if (warningSoundEl) {
      try {
        warningSoundEl.currentTime = 0;
        warningSoundEl.play().catch(function () {});
      } catch (e) {}
      return;
    }

    try {
      const sound = new Audio("/static/sounds/warning.mp3");
      sound.play().catch(function () {});
    } catch (e) {}
  }

  function showWarningPopup(message) {
    const prev = document.getElementById("warning-popup");
    if (prev) prev.remove();

    const popup = document.createElement("div");
    popup.id = "warning-popup";
    popup.innerText = "⚠ " + message;
    popup.style.position = "fixed";
    popup.style.top = "20px";
    popup.style.right = "20px";
    popup.style.background = "#ef4444";
    popup.style.color = "white";
    popup.style.padding = "10px 15px";
    popup.style.borderRadius = "8px";
    popup.style.zIndex = "9999";
    popup.style.boxShadow = "0 6px 18px rgba(0,0,0,0.25)";
    document.body.appendChild(popup);
    setTimeout(function () {
      popup.remove();
    }, 2000);
  }

  function flashScreen() {
    const prev = document.getElementById("warning-flash");
    if (prev) prev.remove();

    const flash = document.createElement("div");
    flash.id = "warning-flash";
    flash.style.position = "fixed";
    flash.style.top = 0;
    flash.style.left = 0;
    flash.style.width = "100%";
    flash.style.height = "100%";
    flash.style.background = "rgba(255,0,0,0.3)";
    flash.style.zIndex = "9998";
    flash.style.pointerEvents = "none";
    document.body.appendChild(flash);
    setTimeout(function () {
      flash.remove();
    }, 200);
  }

  function updateWarningUI() {
    if (warningCountEl) warningCountEl.textContent = String(examState.warningCount);
    if (warningBar) warningBar.classList.toggle("warning-bar-hot", examState.warningCount >= 4);
  }

  function postTelemetry(payload) {
    if (!telemetryUrl) return Promise.resolve(null);
    return fetch(telemetryUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (body) {
        if (!body) return null;
        if (typeof body.warning_count === "number" && body.warning_count > examState.warningCount) {
          examState.warningCount = Math.min(body.warning_count, examState.maxWarnings);
          updateWarningUI();
        }
        if (body.submitted && body.report_url) {
          examState.examEnded = true;
          stopMonitors();
          window.location.href = body.report_url;
        }
        return body;
      })
      .catch(function () {
        return null;
      });
  }

  function goToNextQuestion() {
    const nextIndex = examState.currentQuestion + 1;
    if (nextIndex < examState.totalQuestions) jumpTo(nextIndex);
  }

  function disableOptions() {
    const inputs = optionsEl.querySelectorAll('input[name="answer"]');
    inputs.forEach(function (opt) {
      opt.disabled = true;
      opt.style.pointerEvents = "none";
      opt.style.opacity = "0.6";
    });
    const cards = optionsEl.querySelectorAll(".option-card");
    cards.forEach(function (card) {
      card.style.pointerEvents = "none";
      card.style.opacity = "0.6";
      card.style.cursor = "not-allowed";
    });
  }

  function applyLockStateToCurrentQuestion() {
    if (examState.lockedQuestions && examState.lockedQuestions[examState.currentQuestion]) {
      disableOptions();
    }
  }

  function lockAndNext() {
    if (isLockedNavigating || examState.examEnded) return;
    examState.lockedQuestions[examState.currentQuestion] = true;
    disableOptions();
    isLockedNavigating = true;
    setTimeout(function () {
      isLockedNavigating = false;
      goToNextQuestion();
    }, 1000);
  }

  function addWarning(type, message, questionIndex) {
    const now = Date.now();
    if (examState.examEnded) return;
    if (type !== "Tab" && now - examState.lastWarningTime < 3000) return;

    examState.lastWarningTime = now;
    examState.warningCount += 1;
    examState.warnings.push({
      type: type,
      message: message,
      question: questionIndex + 1,
      time: new Date().toLocaleTimeString(),
    });
    addTimeline("Warning: " + type + " - " + message);

    updateWarningUI();
    playWarningSound();
    showWarningPopup(message);
    flashScreen();
    showLiveAlert(message);

    const payload = {
      warning_type: type,
      warning_reason: message,
      question_number: questionIndex + 1,
    };
    if (type === "Face") payload.face_warning = true;
    if (type === "Voice") payload.multiple_voices = true;
    if (type === "Tab") payload.tab_switch = true;
    if (type === "Screenshot") payload.screenshot = true;
    postTelemetry(payload);

    if (examState.warningCount >= examState.maxWarnings) {
      finishExam("Max warnings reached");
      return;
    }
    lockAndNext();
  }

  function calculateResult() {
    let correct = 0;
    console.log("=== Calculate Result Debug ===");
    console.log("All answers:", examState.answers);
    console.log("Total questions:", examState.totalQuestions);
    
    Object.values(examState.answers).forEach(function (ans, index) {
      console.log(`Answer ${index + 1}:`, ans);
      if (ans && ans.isCorrect === true) {
        correct++;
        console.log(`  -> CORRECT! Total correct: ${correct}`);
      } else {
        console.log(`  -> INCORRECT or missing`);
      }
    });
    
    const result = {
      correct: correct,
      total: examState.totalQuestions,
      percentage:
        examState.totalQuestions > 0
          ? ((correct / examState.totalQuestions) * 100).toFixed(2)
          : "0.00",
    };
    
    console.log("Final result:", result);
    console.log("==========================");
    return result;
  }

  function selectAnswer(option, correctAnswer) {
    if (examState.lockedQuestions && examState.lockedQuestions[examState.currentQuestion]) return;
    
    // Debug logs for comparison
    console.log("=== Answer Comparison Debug ===");
    console.log("Selected option:", option, "Type:", typeof option);
    console.log("Correct answer:", correctAnswer, "Type:", typeof correctAnswer);
    console.log("Strict equality (===):", option === correctAnswer);
    console.log("Case-insensitive equality:", option.toLowerCase() === correctAnswer.toLowerCase());
    console.log("================================");
    
    // Fix case-insensitive comparison
    const isCorrect = option.toLowerCase() === correctAnswer.toLowerCase();
    
    examState.answers[examState.currentQuestion] = {
      selected: option,
      correct: correctAnswer,
      isCorrect: isCorrect,
    };
    
    console.log("Final isCorrect result:", isCorrect);
    console.log("Stored answer:", examState.answers[examState.currentQuestion]);
  }

  function stopMonitors() {
    if (window.faceInterval) {
      clearInterval(window.faceInterval);
      window.faceInterval = null;
    }
    if (activeRecognition) {
      try {
        activeRecognition.onresult = null;
        activeRecognition.onend = null;
        activeRecognition.stop();
      } catch (e) {}
      activeRecognition = null;
      hasVoiceListener = false;
    }
  }

  async function finishExam(reason = "Manual submit") {
  try {
    const root = document.getElementById("exam-root");
    const submitUrl = root.dataset.submitUrl;

    const res = await fetch(submitUrl, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ reason })
    });

    const data = await res.json();

    if (!res.ok) {
        alert(data.message || "Submit failed. Please reload the page.");
        return;
    }

    // SUCCESS -> redirect to report
    if (data.redirect_url) {
        window.location.href = data.redirect_url;
    } else {
        alert("Exam submitted successfully");
        window.location.reload();
    }

  } catch (err) {
    console.error("Submit error:", err);
    alert("Submit failed. Please reload the page.");
  }
}

  function showFinished(score, reportUrl, reason) {
    examActive.classList.add("hidden");
    examFinished.classList.remove("hidden");
    if (reason) {
      const p = examFinished.querySelector("p");
      if (p) p.textContent = reason;
    }
    if (score == null) {
      const p = examFinished.querySelector("p");
      if (p) p.textContent = "Your exam has been submitted.";
    }
    if (reportUrl) window.location.href = reportUrl;
  }

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      video.srcObject = stream;
      if (faceStatusEl) faceStatusEl.innerText = "Camera Active ✅";
      await new Promise(function (resolve) {
        video.onloadedmetadata = function () {
          video.play();
          resolve();
        };
      });
      startFaceDetection();
      return true;
    } catch (err) {
      if (faceStatusEl) faceStatusEl.innerText = "Camera Blocked ❌";
      return false;
    }
  }

  function checkFace(detections) {
    if (!faceStatusEl) return;
    
    const faceTimerEl = document.getElementById("face-timer");
    
    if (detections.length === 0) {
      faceStatusEl.innerText = "Face Not Detected";
      
      if (!faceMissingStart) faceMissingStart = Date.now();
      
      const diff = (Date.now() - faceMissingStart) / 1000;
      const remaining = Math.max(0, 10 - Math.floor(diff));
      
      // Show countdown timer
      if (faceTimerEl) {
        faceTimerEl.classList.remove("hidden");
        faceTimerEl.innerText = `Show your face in ${remaining}s`;
      }
      
      if (diff >= 10) {
        addWarning("Face", "No face detected for 10 seconds", examState.currentQuestion);
        faceMissingStart = null; // Reset timer after warning
        
        // Hide timer after warning
        if (faceTimerEl) {
          faceTimerEl.classList.add("hidden");
        }
      }
      return;
    }
    
    // Face detected - reset and hide timer
    faceMissingStart = null;
    faceStatusEl.innerText = detections.length > 1 ? "Multiple Faces Detected" : "Face Detected";
    
    if (faceTimerEl) {
      faceTimerEl.classList.add("hidden");
      faceTimerEl.innerText = "";
    }
    
    if (detections.length > 1) {
      addWarning("Face", "Multiple faces detected", examState.currentQuestion);
    }
  }

  async function startFaceDetection() {
    if (!video || window.faceInterval) return;
    let modelLoaded = false;
    
    console.log("Starting to load face model...");
    
    try {
      console.log("Loading from /models (Flask route)...");
      await faceapi.nets.tinyFaceDetector.loadFromUri("/models");
      console.log("✅ Model loaded successfully from /models");
      modelLoaded = true;
    } catch (e) {
      console.error("❌ Failed to load model from /models:", e);
      modelLoaded = false;
    }
    
    if (!modelLoaded) {
      console.error("❌ Model failed to load - check Flask route and static files");
      if (faceStatusEl) faceStatusEl.innerText = "Model not loaded ❌";
      return;
    }

    window.faceInterval = setInterval(async function () {
      if (examState.examEnded || !video || video.readyState !== 4) return;
      if (!video.srcObject) return;
      try {
        const detections = await faceapi.detectAllFaces(video, new faceapi.TinyFaceDetectorOptions());
        checkFace(detections);
      } catch (e) {
        if (faceStatusEl) faceStatusEl.innerText = "Face check unavailable ❌";
      }
    }, 1000);
  }

  let speakingFrames = 0;
let silenceFrames = 0;
let lastVoiceWarning = 0;

function analyzeAudio(dataArray) {
    let avg = dataArray.reduce((a, b) => a + b) / dataArray.length;

    if (avg > 70) {
        speakingFrames++;
        silenceFrames = 0;
    } else {
        silenceFrames++;
        if (silenceFrames > 10) speakingFrames = 0;
    }

    // continuous speaking → suspicious
    if (speakingFrames > 30) {
        safeVoiceWarning("voice_activity", "Continuous speaking detected");
        speakingFrames = 0;
    }

    // very loud spike → possible multiple voices
    if (avg > 120) {
        safeVoiceWarning("multiple_voice", "Loud multiple voices suspected");
    }
}

function sendWarning(type, message) {
    const root = document.getElementById("exam-root");
    if (!root) return;

    fetch(root.dataset.telemetryUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            warning_type: type,
            warning_reason: message,
            noise_detected: true
        })
    });
}

function safeVoiceWarning(type, msg) {
    const now = Date.now();

    if (now - lastVoiceWarning < 8000) return;

    lastVoiceWarning = now;
    sendWarning(type, msg);
}

function startVoiceDetection() {
    if (hasVoiceListener) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    hasVoiceListener = true;
    activeRecognition = recognition;

    recognition.onresult = function (event) {
      if (examState.examEnded) return;
      if (examState.voiceCooldown) return;
      
      // Get audio data for analysis
      if (event.results && event.results.length > 0) {
        const result = event.results[event.results.length - 1];
        if (result && result[0]) {
          // Simulate audio data analysis (since we can't access raw audio from Web Speech API)
          // We'll use the confidence and other properties as indicators
          const confidence = result[0].confidence || 0;
          const dataArray = [confidence * 255]; // Convert confidence to audio-like data
          analyzeAudio(dataArray);
        }
      }
      
      const voices = event && event.results ? event.results.length : 0;
      if (voices > 1) {
        examState.voiceCooldown = true;
        addWarning("Voice", "Multiple voices detected", examState.currentQuestion);
        setTimeout(function () {
          examState.voiceCooldown = false;
        }, 5000);
      }
    };

    recognition.onend = function () {
      if (!examState.examEnded && hasVoiceListener && activeRecognition === recognition) {
        try {
          recognition.start();
        } catch (e) {}
      }
    };

    try {
      recognition.start();
    } catch (e) {}
  }

  function renderNav() {
    if (!navGrid || !serverState) return;
    navGrid.innerHTML = "";
    for (let i = 0; i < serverState.total; i++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = String(i + 1);
      btn.className = "qnav-btn";
      const navStatus = serverState.nav_status && serverState.nav_status[i];
      if (i === examState.currentQuestion) btn.classList.add("qnav-btn--current");
      else if (navStatus && navStatus.flagged) btn.classList.add("qnav-btn--flagged");
      else if (navStatus && navStatus.answered) btn.classList.add("qnav-btn--answered");
      else btn.classList.add("qnav-btn--empty");
      btn.addEventListener("click", function () {
        jumpTo(i);
      });
      navGrid.appendChild(btn);
    }
  }

  function renderQuestion() {
    if (!serverState || !serverState.question) return;
    const q = serverState.question;
    examState.currentQuestion = serverState.current_index;
    examState.totalQuestions = serverState.total;
    questionText.textContent = q.text;
    if (questionTopic) questionTopic.textContent = "Topic: " + (q.topic || "General");
    if (progressText) progressText.textContent = "Question " + (examState.currentQuestion + 1) + " / " + examState.totalQuestions;
    if (progressFill) progressFill.style.width = ((examState.currentQuestion + 1) / examState.totalQuestions) * 100 + "%";

    if (timerEl) {
      lastRemaining = serverState.remaining_seconds;
      timerEl.textContent = formatTime(lastRemaining);
      timerEl.classList.toggle("warn", lastRemaining <= 120);
      timerEl.classList.toggle("timer-danger", lastRemaining <= 300);
      timerEl.classList.toggle("timer-blink", lastRemaining <= 60);
    }

    const letters = ["A", "B", "C", "D"];
    optionsEl.innerHTML = "";
    letters.forEach(function (letter) {
      const row = document.createElement("label");
      row.className = "option-card";
      const inp = document.createElement("input");
      inp.type = "radio";
      inp.name = "answer";
      inp.value = letter;
      inp.checked = serverState.selected === letter;
      if (inp.checked) row.classList.add("selected");
      const key = document.createElement("span");
      key.className = "option-key";
      key.textContent = letter + ".";
      const txt = document.createElement("span");
      txt.className = "option-text";
      txt.textContent = q.options[letter];
      row.appendChild(inp);
      row.appendChild(key);
      row.appendChild(txt);

      row.addEventListener("click", function () {
        if (examState.lockedQuestions && examState.lockedQuestions[examState.currentQuestion]) return;
        inp.checked = true;
        const correctAnswer = q.correct_answer;
        selectAnswer(letter, correctAnswer);
        saveAnswer(letter);
        updateSelectedStyles(letter);
      });
      inp.addEventListener("change", function () {
        if (examState.lockedQuestions && examState.lockedQuestions[examState.currentQuestion]) {
          inp.checked = false;
          return;
        }
        const correctAnswer = q.correct_answer;
        selectAnswer(letter, correctAnswer);
        saveAnswer(letter);
        updateSelectedStyles(letter);
      });
      optionsEl.appendChild(row);
    });

    const navStatus = serverState.nav_status && serverState.nav_status[examState.currentQuestion];
    const isFlagged = !!(navStatus && navStatus.flagged);
    if (flagHint) flagHint.textContent = isFlagged ? "Flagged for review" : "";
    if (btnFlag) btnFlag.setAttribute("aria-pressed", isFlagged ? "true" : "false");
    if (btnPrev) btnPrev.disabled = examState.currentQuestion <= 0;
    if (btnNext) btnNext.disabled = examState.currentQuestion >= examState.totalQuestions - 1;
    applyLockStateToCurrentQuestion();
    renderNav();
  }

  function updateSelectedStyles(selected) {
    const rows = optionsEl.querySelectorAll(".option-card");
    rows.forEach(function (row) {
      const inp = row.querySelector('input[type="radio"]');
      // Remove selected from all options
      row.classList.remove("selected");
      // Add selected to the selected one
      if (inp && inp.value === selected) {
        row.classList.add("selected");
      }
    });
  }

  function saveAnswer(letter) {
    if (!serverState || !serverState.question) return;
    if (saveTimer) clearTimeout(saveTimer);
    if (autosaveHint) autosaveHint.textContent = "Saving...";
    saveTimer = setTimeout(function () {
      fetch(answerUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: serverState.question.id, selected: letter }),
      })
        .then(function (r) {
          return r.json().then(function (body) {
            return { ok: r.ok, body: body };
          });
        })
        .then(function (res) {
          if (res.body && res.body.error === "time_up") {
            finishExam("Time up");
            return;
          }
          if (autosaveHint) autosaveHint.textContent = "Saved";
          loadState(false);
        })
        .catch(function () {
          if (autosaveHint) autosaveHint.textContent = "Save failed";
        });
    }, 250);
  }

  function navigate(direction) {
    fetch(navUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction: direction }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (res) {
        if (res.body && res.body.error === "time_up") {
          finishExam("Time up");
          return;
        }
        if (res.ok) loadState(false);
      });
  }

  function jumpTo(index) {
    fetch(navUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jump_to_index: index }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (res) {
        if (res.body && res.body.error === "time_up") {
          finishExam("Time up");
          return;
        }
        if (res.ok) loadState(false);
      });
  }

  function loadState() {
    fetch(stateUrl)
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          questionText.textContent = "Could not load exam. Refresh the page.";
          return;
        }
        if (res.body.finished || res.body.status !== "in_progress") {
          examState.examEnded = true;
          stopMonitors();
          showFinished(res.body.score, res.body.report_url || null);
          return;
        }
        serverState = res.body;
        if (typeof serverState.warning_count === "number") {
          examState.warningCount = Math.min(serverState.warning_count, examState.maxWarnings);
          updateWarningUI();
        }
        renderQuestion();
      })
      .catch(function () {
        questionText.textContent = "Could not load exam. Refresh the page.";
      });
  }

  
  function initExamRuntime() {
    if (initialized) return;
    initialized = true;
    loadState();
    startCamera();
    startVoiceDetection();
    addTimeline("Exam started");
    pollTimer = setInterval(function () {
      if (lastRemaining == null || examState.examEnded) return;
      lastRemaining = Math.max(0, lastRemaining - 1);
      if (timerEl) {
        timerEl.textContent = formatTime(lastRemaining);
        timerEl.classList.toggle("warn", lastRemaining <= 120);
        timerEl.classList.toggle("timer-danger", lastRemaining <= 300);
        timerEl.classList.toggle("timer-blink", lastRemaining <= 60);
      }
      if (lastRemaining <= 0) finishExam("Time up");
    }, 1000);
  }

  // Single listeners
  document.addEventListener("contextmenu", function (e) {
    e.preventDefault();
  });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && ["c", "C", "u", "U", "a", "A"].includes(e.key)) e.preventDefault();
    if (e.key === "PrintScreen" || e.code === "PrintScreen") {
      addWarning("Screenshot", "Screenshot detected", examState.currentQuestion);
    }
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && !examState.examEnded) {
      addTimeline("Tab switched");
      addWarning("Tab", "Tab switched", examState.currentQuestion);
    }
  });

  if (btnPrev) btnPrev.addEventListener("click", function () { navigate("prev"); });
  if (btnNext) btnNext.addEventListener("click", function () { navigate("next"); });
  if (btnSubmit) {
    btnSubmit.addEventListener("click", function () {
      openSubmitModal();
    });
  }
  if (btnFlag && flagUrl) {
    btnFlag.addEventListener("click", function () {
      if (!serverState || !serverState.question) return;
      fetch(flagUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: serverState.question.id }),
      }).then(function () {
        loadState();
      });
    });
  }

  // Exam starts directly without profile confirmation
  initExamRuntime();
})();
