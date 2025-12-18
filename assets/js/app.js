// ========================================
// グローバル変数
// ========================================
let SESSION_ID;
let chatMessages = [];
let conversationId = null;
let currentImage = null;

// ========================================
// 初期化
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 アプリ初期化開始');
    initialize();
    setupImageUpload();
});

// ========================================
// セッションIDを取得または生成
// ========================================
function getOrCreateSessionId() {
    let sessionId = localStorage.getItem('chat_session_id');
    
    if (!sessionId) {
        sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('chat_session_id', sessionId);
        console.log('新しいセッションを作成:', sessionId);
    } else {
        console.log('既存のセッションを復元:', sessionId);
    }
    
    return sessionId;
}

// ========================================
// 初期化関数
// ========================================
async function initialize() {
    console.log('🚀 initialize開始');
    
    SESSION_ID = getOrCreateSessionId();
    loadChatHistory();
    
    try {
        console.log('📡 /api/health リクエスト送信');
        const healthResponse = await fetch('/api/health');
        console.log('📡 /api/health レスポンス:', healthResponse.status);
        
        const healthData = await healthResponse.json();
        console.log('✅ health データ:', healthData);
        
        const dbTypeElement = document.getElementById('dbType');
        if (dbTypeElement) {
            dbTypeElement.textContent = `${healthData.database} | ${healthData.status}`;
        }

        console.log('📡 /api/init リクエスト送信');
        const initResponse = await fetch('/api/init');
        console.log('📡 /api/init レスポンス:', initResponse.status);
        
        const initData = await initResponse.json();
        console.log('✅ init データ:', initData);

        updateStats(initData.stats);
        updatePdfList(initData.pdf_list);
        updateChatHistoryList();

        console.log('✅ 初期化完了');
    } catch (error) {
        console.error('❌ 初期化エラー:', error);
        showError('サーバーに接続できません: ' + error.message);
    }
}

// ========================================
// 統計情報を更新
// ========================================
function updateStats(stats) {
    if (!stats) return;
    
    const pdfCountElement = document.getElementById('pdfCount');
    const totalPagesElement = document.getElementById('totalPages');
    const totalChunksElement = document.getElementById('totalChunks');
    
    if (pdfCountElement) pdfCountElement.textContent = stats.pdf_count || 0;
    if (totalPagesElement) totalPagesElement.textContent = stats.total_pages || 0;
    if (totalChunksElement) totalChunksElement.textContent = stats.total_chunks || 0;
}

// ========================================
// PDF一覧更新
// ========================================
function updatePdfList(pdfList) {
    const listElement = document.getElementById('pdfList');
    if (!listElement) return;
    
    if (!pdfList || pdfList.length === 0) {
        listElement.innerHTML = '<li class="pdf-loading">PDF未登録</li>';
        return;
    }

    listElement.innerHTML = pdfList.map(pdf => `
        <li class="pdf-item">
            <div class="pdf-name">📄 ${escapeHtml(pdf.filename)}</div>
            <div class="pdf-info">
                ${pdf.page_count}ページ | ${pdf.total_chunks}チャンク
            </div>
        </li>
    `).join('');
}

// ========================================
// 画像アップロード機能
// ========================================
function setupImageUpload() {
    const imageUploadBtn = document.getElementById('imageUploadBtn');
    const imageInput = document.getElementById('imageInput');
    const removeImageBtn = document.getElementById('removeImageBtn');
    
    if (!imageUploadBtn || !imageInput) {
        console.warn('⚠️ 画像アップロード要素が見つかりません');
        return;
    }
    
    // 画像アップロードボタンクリック
    imageUploadBtn.addEventListener('click', () => {
        imageInput.click();
    });
    
    // 画像選択時
    imageInput.addEventListener('change', handleImageSelect);
    
    // 画像削除ボタン
    if (removeImageBtn) {
        removeImageBtn.addEventListener('click', clearImage);
    }
}

function handleImageSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    console.log('📷 ファイル選択:', {
        name: file.name,
        size: file.size,
        type: file.type
    });
    
    // ファイルサイズチェック（5MB以下）
    if (file.size > 5 * 1024 * 1024) {
        showError('画像サイズは5MB以下にしてください');
        event.target.value = '';
        return;
    }
    
    // ファイルタイプチェック
    if (!file.type.startsWith('image/')) {
        showError('画像ファイルを選択してください');
        event.target.value = '';
        return;
    }
    
    // Base64に変換してプレビュー表示
    const reader = new FileReader();
    reader.onload = (e) => {
        currentImage = e.target.result;
        
        // デバッグ：Base64形式を確認
        console.log('✅ 画像読み込み完了');
        console.log('📊 Base64先頭:', currentImage.substring(0, 100));
        console.log('📊 Base64長さ:', currentImage.length);
        
        // プレフィックスを確認
        if (currentImage.startsWith('data:image')) {
            console.log('✅ 正しいBase64形式');
        } else {
            console.warn('⚠️ Base64プレフィックスなし');
        }
        
        const imagePreview = document.getElementById('imagePreview');
        const imagePreviewContainer = document.getElementById('imagePreviewContainer');
        
        if (imagePreview) imagePreview.src = currentImage;
        if (imagePreviewContainer) imagePreviewContainer.style.display = 'block';
    };
    reader.readAsDataURL(file);
}

function clearImage() {
    console.log('🗑️ clearImage実行');
    
    currentImage = null;
    
    const imageInput = document.getElementById('imageInput');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    
    if (imageInput) {
        imageInput.value = '';
        console.log('  ✓ imageInput クリア');
    }
    
    if (imagePreviewContainer) {
        imagePreviewContainer.style.display = 'none';
        console.log('  ✓ プレビュー非表示');
    }
    
    console.log('✅ 画像クリア完了');
}

// ========================================
// 質問送信
// ========================================
async function sendQuestion() {
    const input = document.getElementById('questionInput');
    const message = input ? input.value.trim() : '';
    
    // メッセージまたは画像が必要
    if (!message && !currentImage) {
        return;
    }
    
    const sendButton = document.getElementById('sendButton');
    if (!sendButton) return;
    
    const originalHTML = sendButton.innerHTML;
    sendButton.disabled = true;
    sendButton.innerHTML = '<div style="width:20px;height:20px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite;"></div>';
    
    // ウェルカムスクリーンを非表示
    const welcomeScreen = document.querySelector('.welcome-screen');
    if (welcomeScreen) {
        welcomeScreen.style.display = 'none';
    }
    
    // ★ 重要：画像を先に保存してクリア（重複防止）
    const imageToSend = currentImage;
    if (imageToSend) {
        clearImage();  // 即座にクリア
    }
    
    // メッセージを先に追加
    if (message) {
        addMessage(message, true);
    }
    
    // 画像を追加（一度だけ）
    if (imageToSend) {
        addImageMessage(imageToSend, true);
    }
    
    // 入力をクリア
    if (input) {
        input.value = '';
        input.style.height = 'auto';
    }
    
    try {
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                query: message || '',
                conversation_id: conversationId,
                image: imageToSend
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            addMessage(data.response, false);
            conversationId = data.conversation_id;
            
            if (data.stats) {
                updateStats(data.stats);
            }
        } else {
            showError(data.error || '応答の取得に失敗しました');
        }
    } catch (error) {
        console.error('❌ 送信エラー:', error);
        showError('送信に失敗しました: ' + error.message);
    } finally {
        sendButton.disabled = false;
        sendButton.innerHTML = originalHTML;
    }
}
// ========================================
// メッセージ表示
// ========================================
function addMessage(text, isUser) {
    const message = {
        text: text,
        isUser: isUser,
        timestamp: new Date().toISOString()
    };
    chatMessages.push(message);
    addMessageToUI(text, isUser);
    saveChatHistory();
}

function addMessageToUI(text, isUser) {
    const chatContainer = document.getElementById('chatContainer');
    if (!chatContainer) return;
    
    const welcomeScreen = chatContainer.querySelector('.welcome-screen');
    if (welcomeScreen) welcomeScreen.remove();
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = isUser ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const escapedText = escapeHtml(text);
    content.innerHTML = escapedText.replace(/\n/g, '<br>');
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    chatContainer.appendChild(messageDiv);
    scrollToBottom();
}

function addImageMessage(imageSrc, isUser) {
    const chatContainer = document.getElementById('chatContainer');
    if (!chatContainer) return;
    
    // ウェルカムスクリーンを非表示
    const welcomeScreen = chatContainer.querySelector('.welcome-screen');
    if (welcomeScreen) welcomeScreen.remove();
    
    // ★ 重複チェック：同じ画像が既に追加されているか確認
    const existingImages = chatContainer.querySelectorAll('.chat-image');
    for (let img of existingImages) {
        if (img.src === imageSrc) {
            console.log('⚠️ 重複画像を検出、追加をスキップ');
            return;
        }
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = isUser ? '👤' : '🤖';
    
    const img = document.createElement('img');
    img.src = imageSrc;
    img.className = 'chat-image';
    img.alt = 'Uploaded image';
    img.style.maxWidth = '300px';
    img.style.borderRadius = '8px';
    img.style.marginTop = '8px';
    
    // 画像クリックで拡大表示
    img.addEventListener('click', () => {
        window.open(imageSrc, '_blank');
    });
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(img);
    
    chatContainer.appendChild(messageDiv);
    scrollToBottom();
    
    console.log('✅ 画像メッセージを追加しました');
}

function scrollToBottom() {
    const chatWrapper = document.querySelector('.chat-wrapper');
    if (chatWrapper) {
        chatWrapper.scrollTop = chatWrapper.scrollHeight;
    }
}

// ========================================
// 会話履歴管理
// ========================================
function saveChatHistory() {
    try {
        const history = {
            messages: chatMessages,
            lastUpdated: new Date().toISOString(),
            sessionId: SESSION_ID
        };
        localStorage.setItem(`chat_history_${SESSION_ID}`, JSON.stringify(history));
        updateChatHistoryList();
    } catch (error) {
        console.error('会話履歴の保存エラー:', error);
    }
}

function loadChatHistory() {
    try {
        const savedHistory = localStorage.getItem(`chat_history_${SESSION_ID}`);
        if (savedHistory) {
            const history = JSON.parse(savedHistory);
            chatMessages = history.messages || [];
            console.log('📂 会話履歴を復元:', chatMessages.length + '件');
            restoreMessages();
        }
    } catch (error) {
        console.error('会話履歴の読み込みエラー:', error);
        chatMessages = [];
    }
}

function restoreMessages() {
    const chatContainer = document.getElementById('chatContainer');
    if (!chatContainer) return;
    
    const welcomeScreen = chatContainer.querySelector('.welcome-screen');
    if (welcomeScreen) welcomeScreen.remove();
    
    chatMessages.forEach(msg => {
        addMessageToUI(msg.text, msg.isUser);
    });
    
    scrollToBottom();
}

function updateChatHistoryList() {
    const historyList = document.getElementById('chatHistory');
    if (!historyList) return;
    
    const histories = getAllChatHistories();
    
    if (histories.length === 0) {
        historyList.innerHTML = '<div class="chat-history-empty">会話履歴はありません</div>';
        return;
    }
    
    historyList.innerHTML = histories.map(history => {
        const date = new Date(history.lastUpdated);
        const dateStr = formatDate(date);
        const isActive = history.sessionId === SESSION_ID;
        
        return `
            <div class="chat-history-item ${isActive ? 'active' : ''}" 
                 onclick="loadSpecificChatHistory('${history.sessionId}')"
                 data-session-id="${history.sessionId}">
                <span class="chat-history-icon">💬</span>
                <div class="chat-history-content">
                    <div class="chat-history-title">${escapeHtml(history.title)}</div>
                    <div class="chat-history-date">${dateStr}</div>
                </div>
                <button class="chat-history-delete" 
                        onclick="deleteChatHistory(event, '${history.sessionId}')"
                        title="削除">
                    🗑️
                </button>
            </div>
        `;
    }).join('');
}

function getAllChatHistories() {
    const histories = [];
    
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        
        if (key && key.startsWith('chat_history_')) {
            try {
                const data = JSON.parse(localStorage.getItem(key));
                const sessionId = key.replace('chat_history_', '');
                
                if (data.messages && data.messages.length > 0) {
                    const firstUserMessage = data.messages.find(m => m.isUser);
                    const title = firstUserMessage 
                        ? firstUserMessage.text.substring(0, 30) + (firstUserMessage.text.length > 30 ? '...' : '')
                        : '無題の会話';
                    
                    histories.push({
                        sessionId: sessionId,
                        title: title,
                        lastUpdated: data.lastUpdated || new Date().toISOString(),
                        messageCount: data.messages.length
                    });
                }
            } catch (error) {
                console.error('履歴の読み込みエラー:', key, error);
            }
        }
    }
    
    histories.sort((a, b) => new Date(b.lastUpdated) - new Date(a.lastUpdated));
    return histories;
}

function loadSpecificChatHistory(sessionId) {
    if (sessionId === SESSION_ID) return;
    
    try {
        const savedHistory = localStorage.getItem(`chat_history_${sessionId}`);
        if (!savedHistory) {
            showError('会話履歴が見つかりません');
            return;
        }
        
        const history = JSON.parse(savedHistory);
        SESSION_ID = sessionId;
        localStorage.setItem('chat_session_id', sessionId);
        chatMessages = history.messages || [];
        
        const chatContainer = document.getElementById('chatContainer');
        if (chatContainer) chatContainer.innerHTML = '';
        
        restoreMessages();
        updateChatHistoryList();
        
        console.log('✅ 会話履歴を読み込みました:', sessionId);
    } catch (error) {
        console.error('会話履歴の読み込みエラー:', error);
        showError('会話履歴の読み込みに失敗しました');
    }
}

function deleteChatHistory(event, sessionId) {
    event.stopPropagation();
    
    if (!confirm('この会話を削除しますか？')) {
        return;
    }
    
    try {
        localStorage.removeItem(`chat_history_${sessionId}`);
        
        if (sessionId === SESSION_ID) {
            localStorage.removeItem('chat_session_id');
            SESSION_ID = getOrCreateSessionId();
            chatMessages = [];
            
            const chatContainer = document.getElementById('chatContainer');
            if (chatContainer) {
                chatContainer.innerHTML = `
                    <div class="welcome-screen">
                        <div class="welcome-icon">🎓</div>
                        <h1 class="welcome-title">マルチメディア検定<br>学習アシスタント</h1>
                        <div class="quick-actions-grid">
                            <button class="quick-action-card" onclick="sendQuickAction('quiz')">
                                <div class="card-icon">📝</div>
                                <div class="card-title">問題を出す</div>
                                <div class="card-desc">理解度をチェック</div>
                            </button>
                            <button class="quick-action-card" onclick="sendQuickAction('term')">
                                <div class="card-icon">📖</div>
                                <div class="card-title">専門用語解説</div>
                                <div class="card-desc">重要な用語を学ぶ</div>
                            </button>
                            <button class="quick-action-card" onclick="sendQuickAction('past')">
                                <div class="card-icon">📚</div>
                                <div class="card-title">過去問に挑戦</div>
                                <div class="card-desc">試験レベルの問題</div>
                            </button>
                        </div>
                    </div>
                `;
            }
        }
        
        updateChatHistoryList();
        console.log('🗑️ 会話履歴を削除しました:', sessionId);
    } catch (error) {
        console.error('会話履歴の削除エラー:', error);
        showError('会話履歴の削除に失敗しました');
    }
}

// ========================================
// 会話リセット
// ========================================
async function resetConversation() {
    if (!confirm('新しいチャットを開始しますか？\n（現在の会話は保存されます）')) return;

    try {
        await fetch('/api/reset', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: SESSION_ID})
        });

        chatMessages = [];
        localStorage.removeItem(`chat_history_${SESSION_ID}`);
        localStorage.removeItem('chat_session_id');
        SESSION_ID = getOrCreateSessionId();

        const chatContainer = document.getElementById('chatContainer');
        if (chatContainer) {
            chatContainer.innerHTML = `
                <div class="welcome-screen">
                    <div class="welcome-icon">🎓</div>
                    <h1 class="welcome-title">マルチメディア検定<br>学習アシスタント</h1>
                    <div class="quick-actions-grid">
                        <button class="quick-action-card" onclick="sendQuickAction('quiz')">
                            <div class="card-icon">📝</div>
                            <div class="card-title">問題を出す</div>
                            <div class="card-desc">理解度をチェック</div>
                        </button>
                        <button class="quick-action-card" onclick="sendQuickAction('term')">
                            <div class="card-icon">📖</div>
                            <div class="card-title">専門用語解説</div>
                            <div class="card-desc">重要な用語を学ぶ</div>
                        </button>
                        <button class="quick-action-card" onclick="sendQuickAction('past')">
                            <div class="card-icon">📚</div>
                            <div class="card-title">過去問に挑戦</div>
                            <div class="card-desc">試験レベルの問題</div>
                        </button>
                    </div>
                </div>
            `;
        }
        
        updateChatHistoryList();
        console.log('🔄 新しいチャットを開始しました');
    } catch (error) {
        showError('リセットに失敗しました');
    }
}

// ========================================
// ユーティリティ関数
// ========================================
function showError(message) {
    console.error('❌ エラー:', message);
    
    const errorDiv = document.getElementById('errorMessage');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(date) {
    const now = new Date();
    const diff = now - date;
    
    if (diff < 24 * 60 * 60 * 1000 && now.getDate() === date.getDate()) {
        return date.toLocaleTimeString('ja-JP', {hour: '2-digit', minute: '2-digit'});
    }
    
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (yesterday.getDate() === date.getDate()) {
        return '昨日';
    }
    
    return date.toLocaleDateString('ja-JP', {month: 'numeric', day: 'numeric'});
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendQuestion();
    }
}

function sendQuickAction(actionType) {
    const input = document.getElementById('questionInput');
    if (!input) return;
    
    let message = '';
    switch(actionType) {
        case 'quiz':
            message = '問題を出してください';
            break;
        case 'term':
            message = '重要な専門用語を1つ選んで解説してください';
            break;
        case 'past':
            message = '過去問レベルの問題を1問出してください';
            break;
        default:
            return;
    }
    
    input.value = message;
    sendQuestion();
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.classList.toggle('open');
    }
}

// ========================================
// PDFアップロード
// ========================================
async function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showError('PDFファイルを選択してください');
        event.target.value = '';
        return;
    }
    
    if (file.size > 50 * 1024 * 1024) {
        showError('ファイルサイズが大きすぎます（最大50MB）');
        event.target.value = '';
        return;
    }
    
    await uploadPDF(file);
    event.target.value = '';
}

async function uploadPDF(file) {
    const progressDiv = document.getElementById('uploadProgress');
    const progressFill = document.getElementById('progressBarFill');
    const statusText = document.getElementById('uploadStatus');
    
    try {
        if (progressDiv) progressDiv.style.display = 'block';
        if (progressFill) progressFill.style.width = '0%';
        if (statusText) statusText.textContent = 'アップロード中...';
        
        const formData = new FormData();
        formData.append('file', file);
        
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress += 5;
            if (progress <= 90 && progressFill) {
                progressFill.style.width = progress + '%';
            }
        }, 500);
        
        const response = await fetch('/api/upload-pdf', {
            method: 'POST',
            body: formData
        });
        
        clearInterval(progressInterval);
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'アップロードに失敗しました');
        }
        
        const data = await response.json();
        
        if (progressFill) progressFill.style.width = '100%';
        if (statusText) statusText.textContent = '✅ 登録完了！';
        
        setTimeout(() => {
            initialize();
            if (progressDiv) progressDiv.style.display = 'none';
            if (progressFill) progressFill.style.width = '0%';
        }, 2000);
        
    } catch (error) {
        console.error('アップロードエラー:', error);
        showError(`アップロード失敗: ${error.message}`);
        if (statusText) statusText.textContent = '❌ エラー';
        
        setTimeout(() => {
            if (progressDiv) progressDiv.style.display = 'none';
            if (progressFill) progressFill.style.width = '0%';
        }, 3000);
    }
}
// PDF選択API呼び出し
async function confirmSelection() {
    const response = await fetch('/api/select-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversation_id: yourConversationId,
            pdf_name: selectedPdfName
        })
    });
    
    const data = await response.json();
    if (data.success) {
        alert('選択しました: ' + data.selected_pdf);
    }
}
// 画像データを取得
const imagePreview = document.getElementById('imagePreview');
let imageData = null;
if (imagePreview && imagePreview.src && imagePreview.src.startsWith('data:image')) {
    imageData = imagePreview.src.split(',')[1];
}

// 送信時にimageを追加
body: JSON.stringify({
    query: query,
    conversation_id: conversationId,
    image: imageData  // ← この行を追加
})