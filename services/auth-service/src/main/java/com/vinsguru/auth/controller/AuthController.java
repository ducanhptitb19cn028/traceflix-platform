package com.vinsguru.auth.controller;

import com.vinsguru.auth.dto.AccountDto;
import com.vinsguru.auth.dto.AuthResult;
import com.vinsguru.auth.service.AuthService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AuthController {

    private static final Logger log = LoggerFactory.getLogger(AuthController.class);

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @GetMapping("/api/auth/validate")
    public AuthResult validate(@RequestParam(defaultValue = "") String token) {
        log.info("token validation requested");
        return this.authService.validate(token);
    }

    @GetMapping("/api/auth/{userId}")
    public ResponseEntity<AccountDto> account(@PathVariable Integer userId) {
        return this.authService.getAccount(userId)
                               .map(ResponseEntity::ok)
                               .orElseGet(() -> ResponseEntity.notFound().build());
    }

}
