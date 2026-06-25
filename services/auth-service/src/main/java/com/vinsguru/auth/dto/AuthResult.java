package com.vinsguru.auth.dto;

public record AuthResult(boolean valid,
                         String username,
                         String role) {

    public static AuthResult invalid() {
        return new AuthResult(false, null, null);
    }

}
