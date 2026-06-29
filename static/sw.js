// ============================================
// SERVICE WORKER - FAZENDA RECREIO
// ============================================

const CACHE_NAME = 'fazenda-recreio-v2';
const urlsParaCache = [
    '/',
    '/login',
    '/dashboard',
    '/static/css/style.css',
    '/static/images/logo.png',
    '/static/images/logo-192.png',
    '/static/images/logo-512.png'
];

// ============================================
// 1. INSTALAÇÃO
// ============================================
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function(cache) {
                console.log('✅ Arquivos em cache!');
                return cache.addAll(urlsParaCache);
            })
    );
    self.skipWaiting();
});

// ============================================
// 2. ATIVAÇÃO
// ============================================
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.map(function(cache) {
                    if (cache !== CACHE_NAME) {
                        console.log('🗑️ Removendo cache antigo:', cache);
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
    return self.clients.claim();
});

// ============================================
// 3. INTERCEPTAÇÃO - PRIORIDADE: CACHE, DEPOIS REDE
// ============================================
self.addEventListener('fetch', function(event) {
    event.respondWith(
        caches.match(event.request)
            .then(function(response) {
                // Se encontrou no cache, retorna (OFFLINE)
                if (response) {
                    console.log('📦 Servindo do cache:', event.request.url);
                    return response;
                }
                // Se não, busca na rede
                return fetch(event.request)
                    .then(function(response) {
                        // Guarda a resposta em cache para próxima vez
                        var responseClone = response.clone();
                        caches.open(CACHE_NAME)
                            .then(function(cache) {
                                cache.put(event.request, responseClone);
                            });
                        return response;
                    })
                    .catch(function() {
                        // Se offline e não está em cache, mostra página offline
                        console.log('❌ Offline e não está em cache:', event.request.url);
                        return new Response('Você está offline. Conecte-se à internet para acessar.', {
                            status: 503,
                            statusText: 'Offline'
                        });
                    });
            })
    );
});

// ============================================
// 4. SINCRONIZAÇÃO
// ============================================
self.addEventListener('sync', function(event) {
    if (event.tag === 'sync-dados') {
        event.waitUntil(sincronizarDados());
    }
});

async function sincronizarDados() {
    console.log('🔄 Sincronizando dados...');
    try {
        const response = await fetch('/sincronizar');
        const resultado = await response.json();
        console.log('✅ Dados sincronizados:', resultado);
    } catch (error) {
        console.log('❌ Erro ao sincronizar:', error);
    }
}
